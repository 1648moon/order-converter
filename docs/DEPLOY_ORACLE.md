# Oracle Cloud 무료 서버에 배포하기

구성: `직원 브라우저 → Tailscale 사설망 → Oracle VM(Docker: Streamlit 앱)`
인터넷에 공개되는 포트는 **하나도 없습니다**.

## 0. 로컬에서 먼저 확인 (선택)
```bash
pip install -r requirements.txt
APP_PASSWORD=아무거나 streamlit run app.py     # http://localhost:8501
```

## 1. Oracle Cloud 가입 · 서버 생성
1. https://www.oracle.com/kr/cloud/free/ 에서 가입 (해외결제 카드 인증 필요, 무료 범위 안에서는 청구 없음).
   **Home Region은 한국(춘천 또는 서울)** 으로 선택. 가입 후에는 변경 불가.
   가입 화면에 한국이 없으면 일본(오사카·도쿄)이 가깝습니다. 개인정보가 해외 서버를 거치게 되므로 내부 정책과 맞는지 확인하세요.
   주소 칸이 영문만 받으면 `Dongdaemun-gu`처럼 영문으로, City 칸에는 구가 아니라 `Seoul`을 적습니다.
2. 콘솔 → Compute → Instances → Create instance
   - Image: **Ubuntu 24.04** (Canonical Ubuntu)
   - Shape: **VM.Standard.A1.Flex** (Always Free 표시), OCPU 1 / 메모리 6GB 정도면 충분
     (`Out of capacity` 오류가 나면 시간을 두고 재시도하거나 OCPU/메모리를 줄이거나 Availability Domain 변경.
     계정을 Pay-As-You-Go 로 올리면 용량이 풀리는 경우가 많고, Always Free 한도 안에서는 청구되지 않습니다.)
   - 계속 안 되면 AMD 무료 쉐이프 **VM.Standard.E2.1.Micro**(메모리 1GB)로 만들 수 있습니다.
     이 경우 **2단계에서 스왑 2GB 를 반드시 먼저 만드세요**(없으면 빌드·실행 중 메모리 부족). 실제로 이 구성으로 배포·운영 검증했습니다.
   - Networking: 새 VCN + **새 퍼블릭 서브넷**, Public IP 할당 (SSH 접속용으로만 사용).
     생성 화면에서 Public IPv4 토글이 안 켜지면 그대로 만든 뒤 Instance → Attached VNICs → Primary VNIC →
     IPv4 Addresses → Edit → **Ephemeral public IP** 로 붙입니다.
   - SSH keys: 키 쌍을 생성해 **private key 다운로드·보관** (생성 때만 받을 수 있음. 맥이면 `~/.ssh/`에 두고 `chmod 600`)
   - Shielded instance, 블록 볼륨, 백업은 필요 없습니다. 부트 볼륨은 기본 크기로 충분합니다.
3. 보안 목록(Security List)에서 **인바운드는 SSH(22)만** 허용. 8501 등 다른 포트는 열지 않습니다.
   (더 안전하게 하려면 22도 내 공인 IP로 제한, 아래 5단계 후에는 22도 닫아도 됨)

## 2. 서버 접속 · 기본 설정
```bash
ssh -i <private key 파일> ubuntu@<서버 공인 IP>

# (E2.1.Micro 1GB 일 때 필수) 스왑 2GB
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab

sudo apt update && sudo apt -y upgrade
sudo apt -y install unattended-upgrades          # 보안 패치 자동 적용
sudo dpkg-reconfigure -plow unattended-upgrades  # Yes 선택
```

## 3. Docker 설치
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && newgrp docker
docker --version
```

## 4. 앱 올리기
GitHub 비공개 저장소를 쓰는 경우(권장):
```bash
git clone https://github.com/<계정>/<저장소>.git order-converter && cd order-converter
```
저장소 없이 내 맥에서 직접 보낼 때(`input/`, `output/` 등 개인정보 폴더는 제외):
```bash
rsync -av --exclude '.git' --exclude '.venv' --exclude 'input' --exclude 'output' \
  --exclude 'reports' --exclude '.claude' ./ ubuntu@<서버 IP>:~/order-converter/
```

실제 운임 파일과 브랜드명(비공개, git 에 없음)을 서버에 둡니다. 이미지에는 포함하지 않고 읽기 전용으로 마운트합니다:
```bash
# 내 맥에서
ssh <서버> 'umask 077; mkdir -p ~/secrets'
scp config/factory.local.yaml <서버>:~/secrets/factory.local.yaml
```
비밀번호·경로 설정 후 실행:
```bash
cd ~/order-converter
cat > .env <<'EOF'
APP_PASSWORD=긴-비밀번호-입력
BRAND_NAME=브랜드명
FACTORY_LOCAL_YAML=/home/ubuntu/secrets/factory.local.yaml
EOF
chmod 600 .env
chmod 644 ~/secrets/factory.local.yaml   # 컨테이너는 app(uid 1000)으로 실행돼 600이면 읽지 못합니다 (Permission denied)
docker compose up -d --build
docker compose ps          # app 이 running 인지 확인
curl -s localhost:8501/_stcore/health   # ok
```
컨테이너는 `127.0.0.1:8501` 에만 열려 있어 서버 밖에서는 직접 접속할 수 없습니다.

## 5. Tailscale 로 접속 열기
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                       # 출력된 URL 로 로그인해 서버를 내 tailnet 에 등록
sudo tailscale serve --bg 8501          # tailnet 안에서만 HTTPS 로 노출
tailscale serve status                  # https://<서버이름>.<tailnet>.ts.net 주소 확인
```
- 직원 PC·폰에도 Tailscale 앱을 설치하고 같은 계정(또는 초대받은 계정)으로 로그인하면
  위 주소로 접속됩니다. 개인용 무료 플랜은 사용자 3명까지입니다.
- `tailscale funnel` 은 **인터넷 공개**이므로 사용하지 마세요.
- `tailscale serve` 가 "Serve is not enabled on your tailnet" 으로 멈추면 출력된 링크에서 계정에 Serve(HTTPS)를 한 번 켜고 다시 실행합니다.
- Tailscale 관리 화면(Machines)에서 이 서버의 **Disable key expiry** 를 눌러 두세요. 안 하면 약 180일 뒤 서버가 tailnet 에서 끊깁니다.
- 2단계 인증은 Tailscale 이 아니라 로그인에 쓴 계정(Google·GitHub 등)에서 켭니다.
- Tailscale 주소(`100.x.x.x`)로 SSH 가 되는지 확인한 뒤 Oracle 보안 목록에서 22번 포트를 제거하면, 이후 서버는 Tailscale 로만 관리됩니다.

## 6. 운영
| 작업 | 명령 |
|---|---|
| 코드 업데이트 | `git pull && docker compose up -d --build` |
| 로그 보기 | `docker compose logs -f app` |
| 재시작 | `docker compose restart` |
| 중지 | `docker compose down` |

- 재부팅해도 `restart: unless-stopped` 로 앱이 자동으로 다시 켜집니다.
- 서버에는 업로드 파일이 저장되지 않습니다. 파일명만 기록하는 `state` 볼륨(0바이트 파일)만 남고, 날짜가 바뀌면 자동 정리됩니다.
- Oracle은 장기간 거의 사용하지 않는 Always Free 인스턴스를 회수할 수 있습니다.
  코드는 GitHub에 백업해 두면 새 서버에서 4단계만 반복해 복구할 수 있습니다.
- 서버를 옮길 때(예: AWS Lightsail 서울)도 2~5단계는 동일합니다.

## 보안 체크리스트
- [ ] Home Region 한국, 인바운드는 SSH(22)만 (5단계 후 22도 제거)
- [ ] `APP_PASSWORD` 를 충분히 긴 값으로 설정, `.env` 는 git 에 올리지 않음
- [ ] Tailscale 계정에 2단계 인증 설정
- [ ] `tailscale funnel` 사용 안 함
- [ ] unattended-upgrades 활성화
