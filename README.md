# car-watch — 프로젝트카 새 매물 알림

하루 두 번(오전·오후 8시 47분쯤) 엔카·당근을 자동으로 검색해서,
**새로 올라온 매물만** 텔레그램으로 보내주고 핸드폰용 목록 페이지를 갱신해요.
GitHub 서버에서 돌아가서 컴퓨터를 켜둘 필요가 없고, 비용도 들지 않아요.

- 감시 대상: 웨건, 각진 소형 오프로더(레토나·파제로 미니·짐니·랭글러 YJ/TJ·구형 코란도·갤로퍼 숏보디), 작은 SUV
- 자동 제외: 골격(프레임) 손상, 침수, 전손, 도난 (엔카 성능점검·보험이력 기준)
- 당근 매물은 서울·경기·인천 29개 동네 기준으로 찾고, 엔카에도 올라온 같은 차는 엔카 쪽에 "당근에도 있음"으로 묶어요.

## 처음 설정 (한 번만)

### 1. 텔레그램 봇 만들기
1. 텔레그램에서 **@BotFather** 검색 → 대화 시작 → `/newbot` 입력
2. 봇 이름, 아이디(끝이 `bot`)를 정하면 **토큰**이 나와요 (`123456:ABC...` 모양) → 복사
3. 방금 만든 봇과 대화방을 열고 아무 말이나 하나 보내기 (예: `안녕`)
4. 브라우저에서 `https://api.telegram.org/bot<토큰>/getUpdates` 열기
   → 결과 안의 `"chat":{"id": 숫자` 의 **숫자**가 채팅 ID예요

### 2. GitHub에 비밀값 넣기
저장소 → **Settings → Secrets and variables → Actions → New repository secret**
- `TELEGRAM_BOT_TOKEN` = 1번에서 받은 토큰
- `TELEGRAM_CHAT_ID` = 1번에서 찾은 숫자

### 3. 자동 실행 켜기
- **Settings → Actions → General → Workflow permissions** 에서 **Read and write permissions** 선택 → Save
- **Actions** 탭 → 초록 버튼으로 워크플로 사용 허용

### 4. 목록 페이지 켜기
**Settings → Pages → Branch: `main` / 폴더: `/docs`** → Save
몇 분 뒤 `https://<내아이디>.github.io/car-watch/` 에서 열려요. 핸드폰 홈 화면에 추가해두면 편해요.

### 5. 첫 실행
**Actions → 새 매물 확인 → Run workflow**
첫 실행은 지금 있는 매물을 저장만 하고 "감시 시작" 메시지를 보내요. 다음 실행부터는 새로 올라온 차만 알려줘요.

## 조건 바꾸기
`config.json` 을 GitHub 웹에서 연필 아이콘으로 고치면 돼요.
- `max_price`: 최대 가격(만원), `max_km`: 최대 주행거리(km, 제한 없으면 `null`)
- `include` / `exclude`: 모델명·트림에 들어가면 포함/제외할 단어 (`|` 로 구분)
- `daangn_keywords`: 당근에서 검색할 단어
- 실행 시간은 `.github/workflows/watch.yml` 의 `cron` (UTC 기준, 한국시간 −9시간)

## 안 될 때
- 텔레그램에 "응답이 없어요" 알림 → 엔카·당근이 GitHub 서버 접속을 막은 경우예요. 이 경우 집 컴퓨터에서 `python watcher.py` 를 돌리는 방식으로 바꿀 수 있어요.
- Actions 탭에서 실행 기록을 누르면 어디서 멈췄는지 보여요.
- GitHub는 저장소에 60일 동안 활동이 없으면 예약 실행을 멈춰요. 이 프로그램은 실행할 때마다 결과를 저장하니 보통은 문제없어요.
