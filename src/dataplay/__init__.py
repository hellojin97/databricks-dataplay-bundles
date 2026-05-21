"""dataplay 최상위 패키지.

Databricks Asset Bundle 기반 Lakeflow Job 코드를 도메인 서브패키지로 묶는 루트 네임스페이스.
도메인별 비즈니스 로직은 `dataplay.<domain>` 모듈에 두고, 잡 태스크 엔트리포인트는
`dataplay.jobs.<task>` 모듈에 둔다 (헌법 원칙 II — 호출부와 비즈니스 로직 분리).
"""
