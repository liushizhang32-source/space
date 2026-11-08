"""成员2 的视觉模块：绘本页 → ocr.json / vlm.json。

对外只暴露两件事：
- ``run_page(...)``：跑一页，产出契约文件或阶段错误；
- ``backends.build_*``：换模型只换后端，不动流水线。
"""

from .contracts import MODULE_VERSION
from .pipeline import StageError, VisionResult, run_page

__all__ = ["MODULE_VERSION", "StageError", "VisionResult", "run_page"]
__version__ = MODULE_VERSION
