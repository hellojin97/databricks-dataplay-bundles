"""dataplay.wikimedia 도메인 패키지.

위키미디어 변경사항을 bronze 레이어로 적재하는 파이프라인의 비즈니스 로직을 담는다.

모듈 구성:
- `config`  : 외부 입력 검증(Pydantic).
- `window`  : 5분 슬롯/경로 계산과 직렬화 등 순수 변환 함수, IngestWindow 데이터클래스.
- `source`  : MediaWiki Action API 호출 클래스(I/O).
- `writer`  : 볼륨/로컬 디렉터리 적재 클래스(I/O).
- `pipeline`: 위 컴포넌트를 합성하는 orchestrate 함수와 IngestResult.
"""
