# ProjectScan — AI-Assisted Code Editor with GitHub Auto-Sync

## 개요

ProjectScan은 AI와 협업하여 코드를 수정하는 데스크톱 도구입니다. 프로젝트 폴더를 스캔하여 파일 구조와 내용을 AI 프롬프트로 생성하고, AI가 응답한 줄번호 기반 diff를 자동으로 적용하며, 변경 사항을 GitHub에 자동 동기화합니다.

## 주요 기능

### 1. 프로젝트 스캔 및 AI 프롬프트 생성
프로젝트 폴더를 선택하면 파일 트리와 각 파일의 내용을 줄번호 포함하여 하나의 텍스트로 생성합니다. 이 텍스트를 AI에게 전달하면 AI가 프로젝트 전체 구조를 파악할 수 있습니다.

### 2. 줄번호 기반 Diff 적용
AI가 응답한 수정 사항을 줄번호 기반 diff 형식으로 받아 자동 적용합니다. 큰 파일 전체를 다시 붙여넣을 필요 없이 변경된 부분만 정확하게 수정됩니다.

### 3. GitHub 자동 동기화
diff 적용 후 자동으로 git commit & push하여 GitHub 저장소와 동기화합니다. AI는 GitHub URL을 통해 항상 최신 파일을 직접 읽을 수 있으므로, 사용자가 매번 큰 파일을 프롬프트에 포함시킬 필요가 없습니다.

### 4. 롤백
잘못된 수정이 적용된 경우 [Rollback] 버튼으로 이전 커밋으로 되돌리고 GitHub에도 반영합니다.

### 5. 내장 코드 에디터
구문 강조, 줄번호 표시, 파일 직접 편집 및 저장 기능을 제공합니다. Python, JavaScript, C#, VB.NET 등 주요 언어를 지원합니다.

## Diff 형식

AI에게 코드 수정을 요청할 때 아래 형식을 사용합니다:

=== FILE: filename.py === @@ 15-23 REPLACE 새로운 코드 내용 @@ END @@ 50 DELETE 3 @@ 60 INSERT 삽입할 코드 @@ END === END FILE ===


REPLACE는 지정 줄 범위를 교체, DELETE는 지정 줄부터 n줄 삭제, INSERT는 지정 줄 뒤에 코드를 삽입합니다.

## AI 협업 워크플로우

사용자: 프로젝트 스캔 → AI 프롬프트 복사 → AI에게 전달 AI: 코드 분석 → 줄번호 diff 응답 사용자: diff 붙여넣기 → [Apply Diff] 클릭 자동: 파일 수정 → backup 생성 → git commit → GitHub push AI: GitHub에서 최신 파일 읽기 가능


이후 추가 수정이 필요하면 "GitHub에 sync했어요, 파일 읽어보세요"라고만 말하면 AI가 최신 코드를 직접 확인할 수 있습니다.

## 설치 및 실행

### 필수 요구사항
- Python 3.8 이상
- tkinter (Python 기본 포함)
- Git
- GitHub CLI (`gh`) — GitHub 동기화 기능 사용 시

### 실행
python projectscan_ai2.py


### GitHub CLI 인증 (최초 1회)
gh auth login


## 사용법

1. **프로젝트 폴더 선택**: [Select Folder] 버튼으로 프로젝트 폴더를 지정합니다.
2. **스캔**: [Scan] 버튼으로 파일 목록을 불러옵니다.
3. **AI 프롬프트 생성**: [Generate & Copy] 버튼으로 프로젝트 내용을 클립보드에 복사합니다.
4. **AI 응답 적용**: AI의 diff 응답을 Diff 탭에 붙여넣고 [Apply Diff] 클릭합니다.
5. **GitHub 동기화**: GitHub 탭에서 저장소 이름을 입력하고 [Sync to GitHub]를 클릭하거나, Auto-sync를 활성화합니다.
6. **롤백**: 문제 발생 시 [Rollback] 버튼으로 이전 상태로 되돌립니다.

## 기술 스택

- Python, tkinter (GUI)
- Git, GitHub CLI (버전 관리 및 동기화)
- 자체 LineDiffParser / LineDiffEngine (줄번호 기반 diff 파싱 및 적용)
- EncodingHandler (UTF-8, CP949, EUC-KR 등 다중 인코딩 자동 감지)

## 라이선스

MIT License