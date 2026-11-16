"""Deny-by-default asset release; an explicit offline mode preserves Mock demos.

This is containment, not a replacement for production service authentication.
No unreviewed Header, proxy identity or URL token is trusted here.
"""
import os
from pathlib import PurePosixPath, Path
from starlette.staticfiles import StaticFiles
from starlette.responses import JSONResponse


def offline_mock_enabled():
    return (os.environ.get('M1_ASSET_MODE') == 'offline_mock'
            and os.environ.get('M1_DEPLOYMENT_ENV', 'local') == 'local')


class AssetFiles(StaticFiles):
    def __init__(self, *, mode, **kwargs):
        super().__init__(**kwargs)
        self.mode = mode
        self.kind = Path(kwargs['directory']).name

    async def get_response(self, path, scope):
        # Internal artifacts are never released over static HTTP, even in Mock mode.
        name = PurePosixPath(path.replace('\\','/')).name.lower()
        internal = (name.endswith(('_ocr.json','_vlm.json','_refs.json','_c1.json','_c2.json'))
                    or any(x in name for x in ('manifest','sidecar')))
        demo = {'json':('_story.json','_video.json'), 'previews':('_preview.jpg',),
                'audios':('.mp3',), 'videos':('_video.mp4',)}
        if (self.mode != 'offline_mock' or os.environ.get('M1_DEPLOYMENT_ENV', 'local') != 'local' or internal
                or not name.endswith(demo.get(self.kind, ('<never>',)))):
            return JSONResponse({'status':'BLOCKED','reason':'Asset authorization unavailable'},status_code=503)
        # Explicit Mock-only final/demo resources; never a production release path.
        return await super().get_response(path, scope)
