# Założenia, funkcje i zmiany

## 2026-10-12 — pierwsza implementacja

Źródło wymagań: `zalozenia/zalozenia_projektu.mb` oraz przekazane zrzuty podglądu i stanu serwera.

- Logowanie ADMIN z losowym hasłem, scrypt, sesje w ciasteczkach HttpOnly/SameSite, ochrona CSRF i ograniczenie prób logowania.
- Wykrywanie lokalnych urządzeń USB przez V4L2; filtr oddziela węzły obrazu od metadanych. Trwałe ścieżki `/dev/v4l/by-id` rozróżniają kamery i ograniczają skutki zmiany numeracji USB.
- Dodawanie USB z wykrytej listy i IP przez adres strumienia wyłącznie w chronionym API po logowaniu.
- Oddzielne wątki przechwytywania, ponawianie połączeń, MJPEG. Rozpoznawanie najnowszych klatek ze wszystkich kamer we wspólnym wątku z dwoma wątkami ONNX.
- FastALPR: detektor `yolo-v9-t-384-license-plate-end2end`, OCR `cct-xs-v2-global-model`, backend CPU. Źródło API: https://github.com/ankandrew/fast-alpr.
- Wiele wyników na klatkę, głosowanie po przestrzennych śladach, próg 3 skanów / 60% głosów / 80% pewności, okno 12 s.
- Zielona/czerwona strefa przypisana do kamery; środek tablicy klasyfikuje odczyt; walidacja granic i nakładania się stref.
- SQLite z WAL i synchronizacją wątków. Trwała konfiguracja, aktualny parking i historia zdarzeń. Deduplikacja względem aktualnego stanu pojazdu.
- Ciemny panel, siatka 2×2, stronicowanie, powiększenie z edycją stref przez mysz/dotyk, trzy kolumny parkingu.
- Rozwijany stan maszyny po lewej z CPU/RAM/temperaturą/load/RAM procesu/liczbą wątków.
- Prywatne dane w ignorowanych `secret/`, `dsecret/`, `data/`. Rotowany log serwera w `logi/`.

## Technologie i API

Python 3.12, FastAPI/Uvicorn, OpenCV/FFmpeg/V4L2, FastALPR/ONNX Runtime, NumPy, psutil, SQLite; interfejs HTML/CSS/JavaScript bez Node i bez usług CDN. API aplikacji opisano w README. Brak płatnego zewnętrznego API i brak wysyłania obrazu kamer do chmury; modele są pobierane przy pierwszym uruchomieniu, inferencja działa lokalnie.

## Ograniczenia do weryfikacji przy wdrożeniu

Użytkownik potwierdził brak kamer IP na teraz i komunikację baz przez IP ze wspólnym kluczem w secret na obu maszynach. Dodano osobny losowy klucz `secret/integration.key`, API maszynowe tylko do odczytu oraz odbiornik `scripts/pull_events.py` z trwałym kursorem i deduplikacją zdarzeń w SQLite. Adres drugiej maszyny nie został podany: rzeczywistego połączenia między maszynami nie można jeszcze potwierdzić. Jakość rozpoznawania wymaga prób na pojazdach na parkingu. Kamery skierowane na pomieszczenie potwierdzają działanie obrazu, ale nie jakość OCR tablic. Maszyna udostępnia trzy urządzenia wideo typu capture; dwie kamery dostarczają obraz, jedno urządzenie go nie udostępniało podczas testu. Panel uruchomiony na loopback; udostępnienie w LAN wymaga osobnego ustalenia dostępu.

## Weryfikacja

- 7 testów automatycznych zakończonych powodzeniem.
- Przeglądarka Chromium: logowanie, dodanie dwóch konfiguracji USB, działający podgląd jednej dostępnej kamery, edycja/zapis/usunięcie obszaru, rozwijany panel serwera, widok mobilny, wylogowanie.
- Rzeczywisty FastALPR na publicznym obrazie referencyjnym: odczyt zgodny z tablicą na obrazie referencyjnym.
- Dwa równoczesne lokalne strumienie MJPEG w izolowanej bazie: OCR obu kamer, potwierdzony wjazd bez duplikacji, przełączenie stref na wyjazd, potwierdzony wyjazd.
- API integracji sprawdzone lokalnie rzeczywistym odbiornikiem; chronione API bez sesji/klucza zwraca 401.
- Wspólny kontroler obu fizycznych kamer USB odrzuca drugi strumień z `VIDIOC_STREAMON: No space left on device`. Potwierdzono niezależnie od OpenCV przy użyciu v4l2-ctl. Próby MJPEG i YUYV przy niższej rozdzielczości i FPS nie usunęły ograniczenia. Wymagane rozdzielenie kontrolerów USB / poprawa przekazywania USB w wirtualizatorze.

## 2026-10-12 — dostęp przez VPN

Domyślny port zmieniono na 10000. run.sh wykrywa adres IPv4 interfejsu tailscale0 i nasłuchuje na nim; bez interfejsu VPN używa localhost. HOST/PORT nadal pozwalają wybrać adres i port. Poprzedni nasłuch na 127.0.0.1 uniemożliwiał dostęp z innego komputera przez VPN.

Sprawdzenie po zmianie: 7 testów OK; przeglądarka pod http://ADRES_VPN_MASZYNY:10000 wyświetla panel, logowanie i edytor; MJPEG zwraca kompletną klatkę JPEG, OCR działa. Nasłuch potwierdzony na ADRES_VPN_MASZYNY:10000. Tailscale ping do aktywnego komputera zakończony powodzeniem. Test HTTP wykonano z serwera do jego adresu VPN, nie z przeglądarki użytkownika. Druga kamera nadal ma wcześniej opisane ograniczenie kontrolera USB.

## 2026-10-12 — konteneryzacja

Dodano Dockerfile, Compose, docker.sh i prywatny konfigurator urządzeń/portu. Obraz działa jako nieuprzywilejowany użytkownik, z systemem plików tylko do odczytu, bez capabilities i bez mountowania całego /dev. Dostęp do USB jest przekazywany przez osobne mapowania urządzeń wideo i grupy. Adresy, UID/GID i mapowania konkretnego hosta są wyłącznie w ignorowanym dsecret. Baza, hasło, logi oraz modele są trwałe. Montowany jest wyłącznie klucz integracji; klucze GitHuba pozostają poza kontenerem. Dodano trwały katalog modeli i obsługę klucza z mountu tylko do odczytu. Port pozostaje 10000. Przepięcie USB wymaga ponownego wygenerowania mapowań i odtworzenia kontenera.

Weryfikacja Dockera: obraz zbudowany i uruchomiony; healthcheck healthy; 10 testów automatycznych przechodzi. Potwierdzono logowanie, ochronę API, widoczność USB, kompletną klatkę MJPEG, OCR referencyjnego obrazu wewnątrz kontenera oraz podgląd i panel serwera w przeglądarce. Odtworzono kontener i potwierdzono zachowanie hasła, klucza oraz całej konfiguracji kamer wraz ze strefami. Sprawdzono, że sam obraz nie zawiera sekretów, bazy, Gita ani lokalnej .venv. Rozszerzono ignorowanie także na rotowane logi. Stan kontrolera USB pozostaje odrębnym ograniczeniem sprzętu.

## 2026-10-12 — próba naprzemiennego USB

Dodano kolejkę FIFO dla USB. Strumień jest zwalniany przed udzieleniem dostępu następnej kamerze; tura trwa 5 sekund od pierwszej poprawnej klatki. Przechwytywanie IP pozostaje równoczesne. Zatrzymany podgląd zachowuje JPEG i ma oznaczenie; surowa klatka nie jest przekazywana do OCR podczas przerwy. Głosowanie zaczyna się od nowa dla każdej tury, a wynik przetwarzania zakończony po zmianie tury jest odrzucany. Opcja USB_ROTATION_SECONDS=0 pozwala wyłączyć próbę. Dodano test anulowania kolejki i test dwóch pracowników weryfikujący kolejność oraz zamknięcie poprzedniego uchwytu przed otwarciem kolejnego.

Weryfikacja próby: 12 testów automatycznych OK. Ponad 30 sekund obserwacji rzeczywistych kamer potwierdziło nowe klatki JPEG z obu urządzeń, naprzemienne przełączanie i najwyżej jeden aktywny strumień USB. Przeglądarka potwierdziła widoczność obu podglądów i oznaczenia wstrzymanej klatki. OCR pozostaje aktywny. Pięć sekund pracy kamery plus czas ponownego otwarcia daje odstęp między rozpoczęciami kolejnych kamer około 6 sekund. Próba nie zmienia bazy ani zaznaczonych stref.
