# Acro Optical Marketing Studio — 실행 방법

## 처음 한 번만 (이미 해 뒀어요)
```bash
cd ~/Desktop/acro-marketing
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 매번 실행할 때
1. 터미널을 열고 아래를 입력해요.
```bash
cd ~/Desktop/acro-marketing
.venv/bin/python app.py
```
2. 크롬이나 사파리 주소창에 `http://127.0.0.1:5050` 을 입력해요.
3. 끝낼 때는 터미널에서 `control` + `C` 를 눌러요.

## 가족과 같이 쓰기 (같은 와이파이)
1. 터미널에서 `--share` 를 붙여서 실행해요.
```bash
cd ~/Desktop/acro-marketing
.venv/bin/python app.py --share
```
2. 화면에 나오는 `가족 폰·아이패드: http://192.168.x.x:5050` 주소를 가족 기기의 사파리/크롬에 입력해요.
3. 처음 한 번 맥에서 "들어오는 연결을 허용할까요?" 창이 뜨면 **허용**을 눌러요.

주의
- 맥북이 켜져 있고 프로그램이 실행 중일 때만 들어올 수 있어요.
- **같은 와이파이(같은 공유기 네트워크)** 에 있는 기기만 들어올 수 있어요.
- 로그인이 없어서 같은 와이파이에 있는 사람은 누구나 열 수 있어요. 집 와이파이에서만 쓰세요.
- 주소(192.168.x.x)는 가끔 바뀔 수 있어요. 실행할 때 화면에 나오는 주소를 확인하세요.

## 백업
`acro-marketing` 폴더를 통째로 복사하면 끝이에요.
특히 `data/`(데이터)와 `photos/`(사진 원본) 폴더가 중요해요.
