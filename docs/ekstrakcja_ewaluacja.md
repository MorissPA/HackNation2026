# Odczyt cech z dokumentów – llama.cpp / bielik-11b-v2.6-instruct

Czas: 33 s

| Wariant | Pola | Trafne | Częściowo | Błędne | Brak | Wynik pól | Ograniczenia rozpoznane |
|---|---|---|---|---|---|---|---|
| reguły | 19 | 19 | 0 | 0 | 0 | **100.0%** | 100.0% |
| reguły + model | 19 | 19 | 0 | 0 | 0 | **100.0%** | 100.0% |

| Dokument | Wariant | Pola | Nierozpoznane ograniczenia |
|---|---|---|---|
| koncepcja_wodociag_zielony_gaj.txt | reguły | subsector_main: trafne, formula: trafne, remuneration: trafne, budget_pln: trafne, length_km: trafne, connections: trafne, duration_months: trafne | — |
| koncepcja_wodociag_zielony_gaj.txt | reguły + model | subsector_main: trafne, formula: trafne, remuneration: trafne, budget_pln: trafne, length_km: trafne, connections: trafne, duration_months: trafne | — |
| pfu_oczyszczalnia_stare_mlyny.txt | reguły | subsector_main: trafne, remuneration: trafne, budget_pln: trafne, flow_m3d: trafne, duration_months: trafne | — |
| pfu_oczyszczalnia_stare_mlyny.txt | reguły + model | subsector_main: trafne, remuneration: trafne, budget_pln: trafne, flow_m3d: trafne, duration_months: trafne | — |
| aneks_termin_zagrodno.txt | reguły | subsector_main: trafne, deadline_days: trafne | — |
| aneks_termin_zagrodno.txt | reguły + model | subsector_main: trafne, deadline_days: trafne | — |
| protokol_koniecznosci_zlawies.txt | reguły | subsector_main: trafne, extra_cost: trafne, deadline_days: trafne | — |
| protokol_koniecznosci_zlawies.txt | reguły + model | subsector_main: trafne, extra_cost: trafne, deadline_days: trafne | — |
| pismo_termin_grodzisko_ocr.txt | reguły | subsector_main: trafne, deadline_date: trafne | — |
| pismo_termin_grodzisko_ocr.txt | reguły + model | subsector_main: trafne, deadline_date: trafne | — |
