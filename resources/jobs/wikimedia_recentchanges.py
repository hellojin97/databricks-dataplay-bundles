"""Wikimedia RecentChanges 5분 적재 잡의 pydabs 정의.

기존 `wikimedia_recentchanges.yml` 의 1:1 코드 변환. 모듈 최상위 변수 `wikimedia_recentchanges`
가 resource key 로 자동 등록된다 (resources/__init__.py 의 `load_resources` 가 walk_packages
로 발견).

헌법 원칙 I 의 "pydabs 우선" 정책에 따라 본 잡은 Python 으로 정의한다. YAML 정의 대비 이점:
복잡한 분기/반복, 환경별 파라미터 합성, 타입 안전 IDE 지원, 본 레포의 다른 Python 코드와 같은
toolchain (ruff/black/mypy) 사용.
"""

from databricks.bundles.jobs import (
    CronSchedule,
    Environment,
    Job,
    JobEmailNotifications,
    JobEnvironment,
    PauseStatus,
    SparkPythonTask,
    Task,
)

# 잡 태스크에 넘기는 파라미터 — `dataplay.jobs.wikimedia_recentchanges.main` 의 argparse 와 정합.
# 향후 환경(target) 별로 다르게 만들고 싶다면 `@variables` 와 `Variable[str]` 로 전환 가능.
_USER_AGENT = (
    "dataplay-bundles/0.1 "
    "(https://github.com/hellojin97/databricks-dataplay-bundles; contact@example)"
)
_TASK_PARAMETERS = [
    "--wiki-api-url",
    "https://en.wikipedia.org/w/api.php",
    "--wiki-id",
    "en.wikipedia",
    "--volume-root",
    "/Volumes/wikimedia-dataplay/bronze/recentchanges_raw",
    "--user-agent",
    _USER_AGENT,
]


# 모듈 최상위 변수 = resource key. YAML 의 `resources.jobs.wikimedia_recentchanges` 와 동일 키.
wikimedia_recentchanges = Job(
    name="wikimedia_recentchanges",
    # 매 5분 정각(초 0) 자동 트리거 — Databricks 는 Quartz 6-field cron 사용.
    schedule=CronSchedule(
        quartz_cron_expression="0 */5 * * * ?",
        timezone_id="UTC",
        pause_status=PauseStatus.UNPAUSED,
    ),
    # 1 슬롯 = 1 인스턴스. 멱등이지만 동시 실행은 API rate limit 보호상 금지.
    max_concurrent_runs=1,
    tasks=[
        Task(
            task_key="ingest",
            spark_python_task=SparkPythonTask(
                # pydabs 에서는 번들 루트 기준 경로를 사용 (YAML 처럼 정의 파일 기준이 아님).
                # bundle deploy 가 src/ 를 워크스페이스에 업로드한 뒤 해당 경로에서 실행.
                python_file="src/dataplay/jobs/wikimedia_recentchanges.py",
                parameters=_TASK_PARAMETERS,
            ),
            environment_key="default",
        ),
    ],
    environments=[
        JobEnvironment(
            environment_key="default",
            spec=Environment(
                environment_version="2",
                dependencies=[
                    "requests>=2.32,<3",
                    "pydantic>=2.7,<3",
                ],
            ),
        ),
    ],
    # 잡 단위 이메일/Discord 알림은 별도 PR (US3, P3 — research.md R8).
    email_notifications=JobEmailNotifications(on_failure=[]),
)
