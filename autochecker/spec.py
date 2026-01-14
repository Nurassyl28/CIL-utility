# autochecker/spec.py
from typing import Any, Dict, List
from pydantic import BaseModel, Field
import yaml

class CheckSpec(BaseModel):
    """Спецификация одной проверки в YAML."""
    id: str
    type: str
    params: Dict[str, Any] = Field(default_oversampling_factor=1)
    description: str = ""

class LabSpec(BaseModel):
    """Спецификация лабораторной работы (YAML файл)."""
    id: str
    repo_name: str
    checks: List[CheckSpec]

def load_spec(path: str) -> LabSpec:
    """Загружает и валидирует спецификацию из YAML файла."""
    print(f"⚙️ Загрузка спецификации из {path}...")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    spec = LabSpec.parse_obj(data)
    print(f"✅ Спецификация '{spec.id}' успешно загружена. Количество проверок: {len(spec.checks)}")
    return spec
