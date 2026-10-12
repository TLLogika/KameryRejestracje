# KameryRejestracje

Panel w języku polskim do monitorowania kamer USB i IP oraz odczytu wielu tablic rejestracyjnych przez FastALPR.

## Uruchomienie

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

Panel: `http://ADRES_VPN_MASZYNY:10000`. Domyślnie nasłuchuje na adresie IPv4 interfejsu Tailscale (`tailscale0`); bez VPN używa `127.0.0.1:10000`. `HOST` i `PORT` pozwalają ustawić konkretny interfejs i port przy docelowym wdrożeniu. Login `ADMIN`; wygenerowane hasło znajduje się w `dsecret/admin-password.txt`. Hasło nie jest wyświetlane w logach. Weryfikacja używa scrypt; sesje wygasają po 8 godzinach i po restarcie serwera. Zmiany w API wymagają tokenu CSRF. Osiem nieudanych prób logowania blokuje kolejne próby na 5 minut dla danego adresu.

Pierwszy start może pobrać modele rozpoznawania z Internetu. Dostęp do `/dev/video*` wymaga uprawnień systemowych. Zamknij inne programy korzystające z kamer. Usługa ponawia połączenie po utracie obrazu. Adresy IP muszą być dostępne z serwera. Obsługiwane są strumienie RTSP/RTSPS i HTTP/HTTPS obsługiwane przez OpenCV/FFmpeg; wykrywanie kamer IP przez ONVIF nie jest zaimplementowane — adres wpisuje administrator.

## Obsługa

1. Zaloguj się i wybierz „Dodaj kamerę”. Lista USB zawiera urządzenia maszyny z możliwością przechwytywania wideo, a nie urządzenia komputera przeglądarki. Urządzenia zajęte przez inny proces mogą być na liście, ale nie udostępniać obrazu.
2. Kamery są wyświetlane po cztery, w układzie 2×2. Strzałki przełączają kolejne strony.
3. „Powiększ / obszary” otwiera duży podgląd. Wybierz zielony obszar wjazdu/parkingu albo czerwony obszar wyjazdu, przeciągnij po obrazie i zapisz. Strefy nie mogą się nakładać. Można usunąć wybraną strefę. Bez zaznaczonych stref tablice są rozpoznawane, ale nie zmieniają stanu parkingu.
4. Środek wykrytej tablicy określa strefę. Odczyt musi wygrać co najmniej trzy głosy z ostatnich 10 klatek w oknie 12 sekund, mieć co najmniej 60% głosów i pewność OCR co najmniej 80%. Głosowanie odbywa się osobno dla przestrzennych śladów tablic i dla każdej kamery. To próg techniczny, nie gwarancja bezbłędnego OCR — jakość należy sprawdzić na rzeczywistych tablicach i oświetleniu parkingu.
5. Zielona strefa dodaje pojazd do parkingu; czerwona usuwa już obecny pojazd. Powtórzone wjazdy i wyjazdy nie duplikują wpisów. Brak wykrycia nie oznacza automatycznie wyjazdu. Zielona i czerwona strefa muszą odpowiadać rzeczywistemu ruchowi. Kilka kamer obserwujących jednocześnie ten sam pojazd w sprzecznych strefach wymaga poprawienia konfiguracji.
6. Panel serwera rozwija się po lewej: procesor, RAM, temperatura CPU (jeśli czujnik dostępny), load average 1/5/15 minut, RAM całego procesu kamer/panelu i liczba logicznych wątków CPU.

Przechwytywanie działa w osobnym wątku dla każdej kamery. Jeden wspólny proces rozpoznawania analizuje najnowszą klatkę każdej kamery kolejno, bez kolejki zaległych obrazów; modele CPU mają ograniczenie do dwóch wątków. Wszystkie tablice wykryte na danej klatce są przetwarzane. Przy zwiększaniu liczby kamer spada częstotliwość odczytów na kamerę — należy dobrać liczbę kamer i prędkość przejazdu do wydajności maszyny.

## Dane i integracja

`data/parking.sqlite3`: tabele `cameras`, `events`, `parking`, dziennik WAL. Historia pozostaje po restarcie. Baza, hasła i adresy kamer (mogą zawierać dane logowania) nie trafiają do repozytorium.

API wymaga zalogowania do panelu: `POST /api/login` z JSON `{"username":"ADMIN","password":"…"}` zwraca `csrf` i ustawia ciasteczko sesji. Kolejne żądania używają tego ciasteczka; operacje zapisu także nagłówka `X-CSRF-Token`.

- `GET /api/devices`: lokalne urządzenia USB.
- `GET/POST /api/cameras`: lista/dodawanie kamer.
- `PUT /api/cameras/{id}/zones`: prostokąty `arrival`, `departure` ze współrzędnymi `x,y,w,h` w zakresie 0–1.
- `DELETE /api/cameras/{id}`: usunięcie konfiguracji i zatrzymanie przechwytywania.
- `GET /api/cameras/{id}/stream`: podgląd MJPEG, wymaga sesji.
- `GET /api/parking`: trzy listy; historia w interfejsie to ostatnie 100 wpisów każdej kategorii.
- `GET /api/events?after_id=123`: do 1000 zdarzeń rosnąco po ID. Druga maszyna powinna zapamiętać ostatnie odebrane ID i odpytywać dalej. Dostęp dla drugiej maszyny przez wspólny klucz opisano poniżej.
- `GET /api/server`: rzeczywiste pomiary maszyny i stan modeli OCR.

Log operacyjny: `logi/server.log` z rotacją. Dokumentacja założeń, zmian i technologii: `logi/projekt.md`. `secret/` (klucze SSH) i `dsecret/` (hasła, konfiguracja prywatna) są ignorowane przez Git.

## Testy

```bash
.venv/bin/pip install pytest httpx
.venv/bin/python -m pytest -q
```

Testy obejmują wiele tablic, izolację głosów kamer, wygasanie głosów, deduplikację zdarzeń i eksport, trwałość konfiguracji, logowanie, CSRF, walidację USB/IP i zakaz nakładania stref.

## Połączenie dwóch maszyn: IP i wspólny klucz

Klucz integracji jest generowany przy pierwszym starcie w `secret/integration.key` (uprawnienia 600). To osobny klucz od SSH GitHuba. Skopiuj **ten sam plik** bezpiecznie na drugą maszynę do `secret/integration.key`; nie dodawaj go do GitHuba. API maszynowe jest tylko do odczytu danych parkingu i nie daje dostępu do kamer ani ich konfiguracji.

- `GET /api/integration/events?after_id=0`: zdarzenia, do 1000 na żądanie.
- `GET /api/integration/parking`: aktualny parking i ostatnia historia.
- Uwierzytelnianie: nagłówek `Authorization: Bearer <zawartość pliku integration.key>`.

Odbiornik na drugiej maszynie nie wymaga dodatkowych bibliotek:

```bash
python3 scripts/pull_events.py --url https://ADRES_MASZYNY_KAMER --key-file secret/integration.key --db data/cameras.sqlite3 --interval 2
```

Baza odbiorcy zawiera `camera_events`, `camera_parking`, `sync_cursors`. Pierwsze uruchomienie odtwarza parking z historii, następne pobierają nowe zdarzenia od zapisanego ID. Zapis zdarzeń i kursora jest atomowy; ponowne pobranie nie duplikuje rekordów. `--interval 0` wykonuje jeden odczyt maksymalnie 1000 zdarzeń. Długotrwałe odpytywanie dogania większą historię kolejnymi partiami. Zmiana adresu źródła tworzy osobny strumień w bazie odbiorcy. Zmiana klucza wymaga podmiany pliku na obu maszynach i restartu panelu.

Adres maszyny docelowej nie został jeszcze podany. Aktualny panel nasłuchuje na adresie VPN na porcie 10000. Odbiornik konfiguruje się przez `--url http://ADRES_VPN_MASZYNY:10000`. Dostęp z drugiej maszyny wymaga osiągalności adresu VPN i zezwolenia na TCP/10000; do przesyłania klucza przez sieć użyj HTTPS albo zabezpieczonego tunelu.

## Wyniki sprawdzenia na obecnej maszynie

Siedem testów automatycznych przechodzi. Test przeglądarkowy potwierdził logowanie, dodawanie USB, dostępny obraz, rysowanie i zapis stref, panel serwera i układ mobilny. Rozpoznawanie przetestowano na obrazie referencyjnym FastALPR oraz na dwóch jednoczesnych lokalnych strumieniach MJPEG: potwierdzony wjazd, deduplikacja i wyjazd. Lokalny odbiornik połączył się z API przez klucz.

**Obecne dwie kamery USB nie dostarczają obrazu równocześnie na wspólnym kontrolerze.** Sterownik zgłasza `VIDIOC_STREAMON: No space left on device` także przy 320×240/5 FPS i 640×480/5 FPS. To brak zasobów kontrolera USB, nie brak miejsca na dysku. Każda kamera osobno dostarcza obraz. Należy rozdzielić kamery między kontrolery USB albo poprawić konfigurację przekazywania USB do maszyny wirtualnej. Nie zmieniano modułów jądra ani konfiguracji wirtualizatora.
