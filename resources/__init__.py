"""DAB Python 리소스 진입점 (pydabs — `databricks-bundles`).

`databricks.yml` 의 `python.resources` 설정이 본 모듈의 `load_resources` 를 호출한다.
`load_resources_from_current_package_module()` 가 `resources.*` 의 모든 서브모듈을 walk 하며
모듈 최상위에 정의된 `Job` (및 다른 리소스) 객체를 자동 발견한다. 발견된 리소스 키는
모듈 변수명을 그대로 사용 (예: `wikimedia_recentchanges = Job(...)` → resource key
`wikimedia_recentchanges`).

YAML 정의 (`resources/**/*.yml`, `configuration/**/*.yml`) 와 공존 가능 — DAB 가 양쪽을 모두
머지한다.
"""

from databricks.bundles.core import (
    Bundle,
    Resources,
    load_resources_from_current_package_module,
)


def load_resources(bundle: Bundle) -> Resources:
    """Python 으로 정의된 본 번들의 리소스를 로드한다 (DAB CLI 가 호출)."""
    return load_resources_from_current_package_module()
