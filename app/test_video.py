"""Optional local video substitutions; real camera configuration stays in SQLite."""
import json
from pathlib import Path


def load_test_sources(config_file):
    if not config_file or not Path(config_file).is_file():
        return {}
    values=json.loads(Path(config_file).read_text())
    root=(Path(__file__).resolve().parent.parent/'data/test-videos').resolve()
    result={}
    for camera_id,value in values.items():
        path=(root/value['file']).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower()!='.mp4':
            raise ValueError('Nieprawidłowy plik testowy kamery')
        result[int(camera_id)]={'source':str(path),'label':str(value['label'])[:80]}
    return result
