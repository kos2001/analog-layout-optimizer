# 오픈소스 아날로그 설계 도구 적용 내역 (2026-07-20)

GitHub의 오픈소스 아날로그 EDA 도구들을 이 환경에 설치·검증한 기록.

## 설치된 도구

| 도구 | 출처 (GitHub) | 위치 | 역할 | 검증 |
|---|---|---|---|---|
| netgen 1.5.323 (Tcl) | RTimothyEdwards/netgen (소스 빌드) | `~/.local/bin/netgen` (소스: `~/gitspace/eda-tools/netgen`) | 표준 LVS | SKY130 PDK setup으로 배치 LVS → "Circuits match uniquely" |
| KLayout 0.30.9 앱 | KLayout/klayout (brew cask) | `~/Applications/klayout.app` | full PDK DRC deck 실행 | `sky130A_mr.drc` BEOL deck을 OTA GDS에 실행 → 92건 위반 검출 |
| hdl21 7.0.0 + sky130-hdl21 + vlsirtools | dan-fritchman/Hdl21 | bridge venv (`virtuoso-bridge-lite/.venv`) | 프로그래매틱 아날로그 회로 설계 → SPICE | SKY130 diff-pair 모듈 → `sky130_fd_pr__nfet_01v8` 넷리스트 생성 확인 |
| tcl-tk@8, libx11/libxt/libxext | Homebrew | `/opt/homebrew` | netgen 빌드 의존성 | — |

기존에 이미 동작하던 것: ngspice(+SKY130 실제 sim), gdstk, klayout pip 모듈(메탈 서브셋 DRC/LVS), volare PDK(`~/pdk`).

## macOS 특이사항 (중요)

- **KLayout 앱은 `/Applications/KLayout/klayout.app`에 설치되면 몇 분 내 사라짐**
  (unsigned 번들 → macOS 보안이 제거하는 것으로 추정). 해결: 설치 직후
  `~/Applications/klayout.app`으로 복사해 사용. 스크립트도 이 경로를 기본값으로 사용.
- **netgen 빌드**: brew `tcl-tk@8`(8.6) 필요(9.x 비호환), 헤더는
  `include/tcl-tk` 하위라 `CPPFLAGS` 지정 필요, X11은 XQuartz 없이
  brew `libx11/libxt` + `--x-includes/--x-libraries`로 충족,
  clang의 implicit-function-declaration 오류는 `-Wno-implicit-function-declaration`으로 우회.
- xschem/magic은 X11 GUI 의존이 커서 보류. 전체 GUI 플로우가 필요하면
  iic-jku/IIC-OSIC-TOOLS Docker 이미지(ARM64 지원)가 최단 경로.

## 사용법

```bash
# full SKY130 BEOL DRC (프로젝트 스크립트)
layout_opt_poc/scripts/run_sky130_drc.sh <input.gds> <top_cell> [report.lyrdb]

# netgen LVS (SKY130 setup)
~/.local/bin/netgen -batch lvs "a.spice top" "b.spice top" \
  $PDK_ROOT/sky130A/libs.tech/netgen/sky130A_setup.tcl out.rpt
```
