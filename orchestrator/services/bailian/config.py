"""Nonsecret configuration and versioned official capability catalogue."""
from datetime import date
from decimal import Decimal,ROUND_CEILING
from pydantic import BaseModel,ConfigDict,Field,model_validator

RESEARCH_DATE='2026-11-17'
PRICE_SOURCE='https://help.aliyun.com/zh/model-studio/model-pricing'
REGIONS={
 'cn-beijing':dict(label='华北2（北京）',host='dashscope.aliyuncs.com'),
 'ap-southeast-1':dict(label='新加坡',host='dashscope-intl.aliyuncs.com'),
}
class ModelConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    region:str='cn-beijing'
    workspace:str=Field(default='',pattern=r'^[a-zA-Z0-9_-]{0,64}$')
    vlm_model:str='qwen3-vl-plus'
    llm_model:str='qwen-plus'
    agent_model:str='qwen-plus'
    asr_model:str='qwen3-asr-flash'
    tts_model:str='cosyvoice-v3-flash'
    tts_voice:str='longyan_v3'
    voice_alias:str='storybook_female_warm'
    wan_model:str='wan2.6-i2v-flash'
    speech_rate:float=Field(default=.9,ge=.5,le=2)
    resolution:str='720P'
    request_timeout:int=Field(default=90,ge=5,le=180)
    video_timeout:int=Field(default=1800,ge=60,le=7200)
    poll_seconds:int=Field(default=15,ge=5,le=60)
    get_retries:int=Field(default=2,ge=0,le=3)
    vlm_max_tokens:int=Field(default=1600,ge=100,le=3000)
    story_max_tokens:int=Field(default=16000,ge=1000,le=30000)
    agent_max_tokens:int=Field(default=600,ge=100,le=1200)
    narration_chars_per_page:int=Field(default=90,ge=30,le=120)
    shots_per_page:int=Field(default=2,ge=1,le=4)
    global_budget_fen:int=15000
    search_enabled:bool=False
    @model_validator(mode='after')
    def validate_selection(self):
        if self.region not in REGIONS:raise ValueError('Unsupported region')
        if self.global_budget_fen!=15000:raise ValueError('Project budget is fixed at 15000 fen')
        if self.search_enabled:raise ValueError('Web search is not enabled in this release')
        if self.resolution not in {'720P','1080P'}:raise ValueError('Wan resolution must be 720P/1080P')
        return self
    @property
    def api_base(self):
        host=f'{self.workspace}.{self.region}.maas.aliyuncs.com' if self.workspace else REGIONS[self.region]['host']
        return 'https://'+host
    @property
    def compatible_base(self):return self.api_base+'/compatible-mode/v1'
    def readiness(self):
        problems=[]
        if self.region!='cn-beijing':problems.append('本轮核实的CosyVoice非实时HTTP全链路默认北京地域；其他地域须单独核实能力与价格')
        if self.vlm_model!='qwen3-vl-plus' or self.llm_model!='qwen-plus' or self.agent_model!='qwen-plus':problems.append('所选型号尚无本版本核实的费用上界；补齐价格配置后才允许计费')
        if self.tts_model!='cosyvoice-v3-flash' or self.tts_voice not in {'longyan_v3','longanhuan'}:problems.append('所选CosyVoice型号/音色未通过本版本目录校验')
        if self.wan_model!='wan2.6-i2v-flash':problems.append('所选Wan型号的时长/价格约束未配置')
        return problems

def ceil_fen(yuan):return int((Decimal(str(yuan))*100).quantize(Decimal('1'),rounding=ROUND_CEILING))
def price_estimate(config,pages):
    """Conservative planning bounds, never actual provider billing evidence."""
    problems=config.readiness()
    if problems:raise ValueError('；'.join(problems))
    count=len(pages)
    if not 1<=count<=30:raise ValueError('Book must contain 1..30 pages')
    # A 32K VLM input ceiling and bounded output include image token overhead.
    vlm=Decimal(count)*(Decimal(32000)*Decimal('1')+Decimal(config.vlm_max_tokens)*10)/1_000_000
    # Reserve highest supported token tier, not a guessed promotional discount.
    llm=(Decimal(128000)*Decimal('4.8')+Decimal(config.story_max_tokens)*48)/1_000_000
    narration=count*config.narration_chars_per_page
    tts=Decimal(narration)/10000
    # Plan against a slow reading bound, split narration before TTS and fit each
    # utterance to verified audio duration before any Wan submission.
    seconds=count*config.shots_per_page*15
    video=Decimal(seconds)*({'720P':Decimal('.15'),'1080P':Decimal('.25')}[config.resolution])
    total=ceil_fen((vlm+llm+tts+video)*Decimal('1.2'))
    return dict(estimate_fen=total,reserved_seconds=seconds,max_narration_chars=narration,
        breakdown_fen=dict(vlm=ceil_fen(vlm),llm=ceil_fen(llm),tts=ceil_fen(tts),wan=ceil_fen(video)),
        price_checked_on=RESEARCH_DATE,price_source=PRICE_SOURCE,billing_status='ESTIMATE_NOT_SETTLED',
        currency='CNY',pages=count,cloud_data=['页面图片','OCR文字','故事上下文','配音文本'])
