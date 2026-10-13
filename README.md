# KameryRejestracje

Prosty panel parkingu: kamery USB/IP, zielone i czerwone obszary, OCR z potwierdzeniem w co najmniej trzech różnych klatkach, SQLite oraz dwa widoki — **Kamery** i **Baza danych**. Logowanie: `ADMIN`.

## Windows — Docker Desktop

Włącz kontenery Linux w Docker Desktop. Repozytorium można [pobrać jako ZIP](https://github.com/TLLogika/KameryRejestracje/archive/refs/heads/main.zip); Git i Python na hoście nie są potrzebne do uruchomienia panelu z kamerami IP.

Rozpakuj projekt, otwórz PowerShell w jego katalogu i uruchom:

```powershell
powershell -ExecutionPolicy Bypass -File .\docker.ps1
```

`Bypass` dotyczy tego wywołania PowerShell. Skrypt tworzy katalogi trwałe i klucz, buduje obraz i czeka na zdrowy kontener. Aplikacja sama tworzy hasło administratora i bazę. **Nie trzeba ręcznie edytować Compose, generować bazy ani zmieniać mountu klucza na zapis.**

Panel: `http://127.0.0.1:10000`. Hasło: `dsecret/admin-password.txt`. Istniejące dane, hasło i klucz pozostają zachowane.

```powershell
powershell -ExecutionPolicy Bypass -File .\docker.ps1 -Command logs
powershell -ExecutionPolicy Bypass -File .\docker.ps1 -Command down
```

Domyślnie panel jest dostępny lokalnie. Inny adres interfejsu IPv4 i port można ustawić przed uruchomieniem przez `PANEL_BIND_IP` i `PANEL_PORT`; skrypt zapisuje je wyłącznie w ignorowanym `dsecret/docker-windows.env`.

### Kamery USB na Windowsie

Docker Desktop nie przekazuje bezpośrednio kamer USB Windows do kontenera Linux. [Dokumentacja Docker](https://docs.docker.com/desktop/troubleshoot-and-support/faqs/general/). Projekt ma opcjonalny **mostek USB**, który używa DirectShow na Windowsie i przesyła listę urządzeń oraz obraz do aplikacji. Sekret jest wysyłany w nagłówku uwierzytelnienia, a nie w adresie strumienia.

Mostek wymaga Python 3 z poleceniem `py` na Windowsie; zalecany Python 3.12. Zamknij inne programy używające tych kamer. W pierwszym oknie PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows-usb.ps1
```

Pierwszy start instaluje tylko biblioteki potrzebne do USB w osobnym `.venv-usb`. Zostaw to okno otwarte. W drugim oknie:

```powershell
powershell -ExecutionPolicy Bypass -File .\docker.ps1 -UsbBridge
```

Po zalogowaniu wybierz **Dodaj kamerę → USB → Odśwież listę USB**. Kamery Windows są oznaczone „USB Windows”. Nie jest potrzebne mapowanie `/dev/video*` ani konfiguracja sterowników WSL. Mostek używa portu 10001 i klucza w `dsecret/usb-bridge.key`; port musi być osiągalny z Docker Desktop. Nie otwieraj mostka w publicznym internecie. To opcja tylko dla lokalnych USB; kamery IP nie wymagają mostka.

Dla ograniczonej przepustowości USB można uruchomić mostek z niższą rozdzielczością:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows-usb.ps1 -Width 640 -Height 480 -Fps 15
```

### Alternatywa: bezpośrednie USB przez Linux/WSL

Przekazywanie USB/IP wymaga właściwego kernela/sterownika i urządzenia widocznego w systemie, na którym działa silnik Docker. Samo `usbipd attach --wsl` nie gwarantuje pojawienia się `/dev/video*` w Docker Desktop. Oficjalna instrukcja Docker USB/IP opisuje Windows z backendem Hyper-V i nie gwarantuje obsługi każdej kamery. [Microsoft: USB w WSL](https://learn.microsoft.com/en-us/windows/wsl/connect-usb), [Docker: USB/IP](https://docs.docker.com/desktop/features/usbip/). W tej konfiguracji użyj instrukcji Linux dopiero po potwierdzeniu obecności urządzeń w silniku Docker.

## Linux — Docker Engine

Wymagane: Docker Compose i Python 3. W katalogu projektu:

```bash
python3 scripts/configure_docker.py
./docker.sh up -d --build --wait
```

Konfigurator zapisuje UID/GID, adres interfejsu i mapowania urządzeń w prywatnym `dsecret`. Wybiera interfejs VPN Tailscale, jeśli istnieje; w przeciwnym razie localhost. Port domyślny: 10000. Hasło jest w `dsecret/admin-password.txt`.

Po dołączeniu lub przepięciu kamery odśwież urządzenia przekazywane do kontenera:

```bash
./docker.sh refresh-usb
./docker.sh up -d --force-recreate --wait
```

Lista kamer filtruje węzły metadanych, odróżnia urządzenia fizyczne i preferuje stabilne nazwy. Urządzenia bez uprawnień są oznaczone jako niedostępne. Wykrywanie nie uruchamia strumieni i nie zajmuje kamer innym aplikacjom.

## Używanie panelu

1. Zaloguj się i dodaj USB dostępne serwerowi albo adres RTSP/RTSPS/HTTP/HTTPS kamery IP.
2. W **Kamery → Powiększ / obszary** narysuj zielone obszary wjazdu oraz czerwone wyjazdu i zapisz. Można dodać po 32 obszary każdego koloru. Przeciwne kolory nie mogą się nakładać.
3. Środek tablicy wyznacza obszar. Odczyt wymaga co najmniej trzech zgodnych głosów z różnych przechwyconych klatek, pewności OCR ≥80% i co najmniej 60% zgodnych głosów w oknie do 12 sekund. Powtórzone zdarzenia nie duplikują stanu parkingu.
4. **Baza danych** pokazuje aktualny parking oraz ostatnie 100 wjazdów i 100 wyjazdów. Można wyszukiwać rejestracje. Ten widok zamyka podglądy w przeglądarce; OCR działa dalej. Adres z `#database` otwiera bezpośrednio bazę.
5. **Ustawienia kamer**, pod bazą danych, zawierają przełącznik pracy naprzemiennej USB, wybór kamery, właściwości i parametry obrazu. Checkbox odznaczony: równoczesne pobieranie wszystkich kamer; zaznaczony: kamery USB kolejno, z osobnymi czasami tur. Ustawienie jest trwałe i działa także z mostkiem Windows. Rozdzielczość i FPS USB Windows ustawiasz w mostku. Kamery IP i testowe pracują równocześnie.
6. **Dodaj kamerę → Kamera testowa** pozwala wybrać Car Park lub Parking Garage. Oba nagrania Full HD / 60 FPS są częścią repozytorium i obrazu Docker. Car Park trwa około 40 s (spowolnienie 4× z powtórzeniem klatek), Parking Garage około 19 s. Pliki odtwarzają się w pętli; odczyty trafiają do osobnej bazy testowej. Przy samych kamerach testowych widok bazy pokazuje bazę testową; przy mieszanych kamerach pokazuje właściwy parking. Integracja zawsze czyta właściwą bazę.
7. **Stan serwera** jest rozwijany na dole lewego menu.

Kamery domyślnie działają równocześnie. **Podmiana starych kamer na nagrania i przełączanie USB są domyślnie wyłączone**, także gdy w katalogu znajdują się stare nagrania lub pliki próby.

## Wydajność i CPU

W **Ustawienia kamer → Wydajność i zużycie CPU** są trzy profile oraz ręczne ustawienia. Nowe wdrożenia i wdrożenia bez zapisanych ustawień wydajności zaczynają od oszczędnego: podgląd 5 FPS / maks. 640 px / JPEG 55, do 2 analiz OCR/s na kamerę i jeden wątek analizy.

| Opcja | Co zmienia |
| --- | --- |
| Limit FPS, szerokość i jakość JPEG | Koszt skalowania/kodowania oraz transmisję podglądu; OCR zachowuje pełną klatkę. |
| Podgląd tylko dla aktywnych widzów | Domyślnie włączone. Bez otwartych strumieni serwer nie tworzy JPEG; kamery i OCR nadal pracują. JPEG jest współdzielony przez wszystkich widzów danej kamery. |
| Włącz podgląd | Pozwala wyłączyć cały podgląd, zachowując analizę. |
| Maksimum analiz/s na kamerę | Ogranicza liczbę uruchomień OCR. Rzeczywista szybkość może być niższa; trzy zgodne odczyty w różnych klatkach nadal są wymagane. |
| Wątki CPU analizy | 1–8, nie więcej niż logicznych CPU. Zmiana przeładowuje modele, chwilowo zatrzymując OCR; kamery pozostają aktywne. |
| Włącz rozpoznawanie | Pauza OCR i nowych zdarzeń bez usuwania bazy; pozwala także porównać zużycie CPU z samym obrazem. |

Przy limicie 2 analiz/s odstęp pomiędzy pierwszą a trzecią analizą wynosi co najmniej 1 s. Przy szybkim przejeździe zwiększ limit. Ustawienia są trwałe i dotyczą wszystkich kamer. Limit OCR nie jest limitem procentowym CPU. Kamera IP może nadal wymagać dekodowania całego strumienia: rozdzielczość/FPS źródła zmień w kamerze, a dla USB użyj wyboru parametrów poniżej.

**Stan serwera** pokazuje CPU całej maszyny i osobno CPU aplikacji (100% oznacza jeden zajęty rdzeń, więc aplikacja może przekroczyć 100%). Właściwości kamer pokazują FPS i czas kodowania podglądu, liczbę widzów oraz limit i rzeczywistą szybkość OCR.

## Dane i budowa programu

- `data/` — SQLite i cache modeli; `dsecret/` — hasło, hash i konfiguracja; `logi/` — logi.
- `secret/integration.key` — istniejący klucz integracji, montowany tylko do odczytu.
- `app/devices.py` — wykrywanie USB; `capture.py` — obraz; `ocr.py` — rozpoznawanie; `cameras.py` — uruchamianie/zatrzymywanie kamer; `store.py` — SQLite; `main.py` — uwierzytelnienie i HTTP.
- `app/optional/` — funkcje próbne. Mostek Windows jest osobnym narzędziem hosta i nie instaluje OCR na Windowsie.

Kontener działa bez `privileged`, z obrazem tylko do odczytu i trwałymi katalogami. Na Linuxie uprawnienia są sprawdzane ściśle; dla bind mountów Windows skrypt wybiera tryb przenośny, tolerujący tylko brak obsługi zmiany uprawnień. Błędy odczytu/zapisu nie są ukrywane. Dostęp do katalogu projektu na Windowsie regulują uprawnienia NTFS.

Dane wdrożenia, klucze, hasła, prywatne nagrania i baza nie trafiają do repozytorium ani obrazu. Publiczne nagrania testowe w `app/demo/` są dołączone na licencji [CC BY 4.0; źródło i autorzy](app/demo/ATTRIBUTION.md). Pierwszy start pobiera modele rozpoznawania; kolejne korzystają z cache. Skuteczność i szybkość odczytu trzeba sprawdzić na docelowych kamerach i oświetleniu.

[Opcjonalne próby, integracja i zaawansowane ustawienia](docs/advanced.md).
