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

## 2026-10-12 — indywidualne parametry kamer

Dodano ustawienia JSON w tabeli cameras z migracją istniejącej bazy. Każda kamera USB ma osobny czas tury oraz tryb rozdzielczość/format/FPS, wybierany spośród trybów urządzenia przez V4L2. API waliduje kombinacje oraz minimalny czas: co najmniej 3 s i dynamiczny próg czterech cykli analizy z zapasem 0,5 s. Zmiana powoduje ponowne otwarcie strumienia przy zachowaniu kolejki USB i istniejącego połączenia podglądu. Dodano pomiary rzeczywistej rozdzielczości, FPS sterownika, FPS przechwytywania, OCR/s, czasu analizy, wieku klatki i czasu do końca tury. Panel wyświetla metryki i formularz w powiększonym podglądzie. IP ma metryki, lecz bez zmiany parametrów kodera. Ustawienia i adresy pozostają w prywatnej bazie; dokumentacja nie zawiera rzeczywistych adresów sprzętu.

Weryfikacja: 15 testów automatycznych przechodzi, w tym migracja bazy bez utraty stref, trwałość ustawień, walidacja trybów i dynamicznego minimum oraz zero bieżących FPS w pauzie. Na fizycznej kamerze potwierdzono zmianę na 640×480 i 10 FPS bez restartu kontenera, niezależne czasy tur i pomiary OCR. Przeglądarka potwierdziła metryki, wybór obsługiwanych trybów, zapis czasu i poprawny układ mobilny. Po próbie przywrócono wcześniejsze parametry; strefy pozostały bez zmian.

## 2026-10-12 — wiele obszarów detekcji

Dodano do 32 obszarów każdego koloru na kamerę. API przyjmuje listy oraz dawny format pojedynczego prostokąta; istniejące zaznaczenia nie są usuwane. Edytor numeruje obszary, dodaje kolejne zaznaczenia, pozwala wybrać obszar do przerysowania oraz usunąć pojedynczy element. Zielone i czerwone obszary nie mogą się nakładać; nakładanie tego samego koloru jest dozwolone i klasyfikowane jednokrotnie. Punkt tablicy jest sprawdzany względem wszystkich zapisanych obszarów. Dodano testy wielu stref, zgodności ze starym formatem, trwałości, walidacji granic i potwierdzania tablic w różnych strefach.

Weryfikacja: 17 testów automatycznych; próba w przeglądarce — dodanie dwóch obszarów każdego koloru, usunięcie pojedynczego, edycja wybranego, ponowne otwarcie i widok mobilny. Poprzednie obszary kamery przywrócono po próbie.

Dodano odwracalną podmianę dwóch kamer USB na lokalne podglądy MP4 UVG-VCM: Car Park i Parking Garage (CC BY 4.0, źródło i autorzy w README). Pobrane MP4 zajmują łącznie około 195 MB, kopie robocze 1080p/15 FPS około 61 MB. Dane i prywatny plik podmiany są wyłączone z Git i obrazu Docker. Nagrania odtwarzają się równocześnie w pętli i mają etykietę TEST; odczyty nie dopisują zdarzeń do bazy parkingu.

Weryfikacja: 20 testów automatycznych; pełne dekodowanie kopii bez błędów; działający kontener i próba przez przeglądarkę z dwoma różnymi podglądami, wykryciami OCR na obu, edytorem oraz zachowanymi źródłami/ustawieniami USB. Liczba zdarzeń parkingowych pozostała bez zmian. Na tej maszynie zmierzono około 6–8 FPS przechwytywania i około 0,4 analizy OCR/s na kamerę.

Przyspieszono podgląd i analizę: całkowity współczynnik skalowania JPEG (dla klatki 1080p podgląd 960×540), pojedynczy wątek dekodera FFmpeg, wyłączone aktywne oczekiwanie ONNX Runtime, pętla bez dodatkowych 250 ms przerwy i strumień HTTP sprawdzany co 25 ms. Filmy testowe używają detektora 256×256 na obszarze drogi skalibrowanym z granic adnotacji; OCR analizuje rzeczywiste wycinki klatek. Fizyczne kamery nadal używają modelu 384×384 na całym obrazie.

Car Park wydłużono z 10 do 40 sekund: 600 kolejnych oryginalnych klatek, odtwarzanych przy 15 FPS. Potwierdzenia z trzech przechwyconych klatek trafiają do osobnej bazy testowej; przy wszystkich kamerach testowych panel pokazuje tę bazę i wyraźne oznaczenie TEST. Integracja nadal czyta właściwą bazę. W edytorze widoczne są rozdzielczości podglądu i klatki, obszar/model analizy oraz liczba potwierdzeń.

Weryfikacja: 23 testy automatyczne; w pomiarze dwóch równoległych nagrań mediana przechwytywania 15 FPS na kamerę, mediana OCR 3,0/s (zakres 2,1–3,2/s). Potwierdzenia wystąpiły na obu kamerach, powstały wpisy w bazie testowej, a właściwa baza pozostała bez zmian. Na polecenie użytkownika zatrzymano kontener na porcie 9000 oraz, po osobnym potwierdzeniu, natywną usługę na porcie 8080.

Dodano zakładkę „Baza danych” w lewym menu: przyjazdy, aktualny parking i odjazdy bez obrazów kamer, filtrowanie po rejestracji, liczniki, czas/kamera/pewność odczytu i oznaczenie bazy testowej. Historia obejmuje ostatnie 100 wpisów każdej kategorii. Widok jest zapamiętany przez #database; wejście bezpośrednio po zalogowaniu nie otwiera strumieni. Przełączenie z kamer usuwa źródła obrazów i zamyka transmisję, pozostawiając OCR na serwerze.

Weryfikacja przeglądarką: wyszukiwanie, zero strumieni przy wejściu do bazy, przełączanie kamer, zatrzymanie napływu danych wideo sprawdzone przez Chrome DevTools Protocol, brak ponownego otwarcia podczas odświeżania danych i strony, poprawny widok mobilny oraz brak błędów JavaScript. Kontener zdrowy; kontrola publicznych plików przeszła.

## 2026-10-13 — uproszczenie i Docker na Windowsie

Podstawowy panel obejmuje kamery USB/IP, wiele obszarów, potwierdzenie OCR w trzech różnych klatkach, SQLite, logowanie oraz widoki kamer i bazy. Zaawansowane metryki i ustawienia są zwinięte; naprzemienne USB i nagrania testowe są domyślnie wyłączone. Oddzielono przechwytywanie, OCR, wykrywanie urządzeń i funkcje opcjonalne. Wykrywanie USB odrzuca węzły metadanych, usuwa duplikaty i pokazuje brak uprawnień.

Dodano launcher PowerShell tworzący katalogi i klucz oraz przenośną obsługę uprawnień bind mountów. Klucz integracji pozostaje tylko do odczytu. Opcjonalny mostek Windows udostępnia fizyczne USB kontenerowi przez uwierzytelniony MJPEG; klucz jest w nagłówku, a nie w URL.

Weryfikacja: 34 testy automatyczne, wykonanie launchera w PowerShell z atrapą Dockera, zbudowanie obrazu oraz odizolowany test kontenera z dwoma strumieniami mostka, logowaniem, SQLite, obszarami, przeglądarką i trwałością po restarcie. Test przenośnych uprawnień obejmował klucz zamontowany tylko do odczytu. Fizyczne urządzenia i sterowniki USB na Windowsie wymagają sprawdzenia na komputerze Windows; próba mostka używała syntetycznych klatek. Usługi na portach 8080 i 9000 pozostawiono działające, parking na 10000 wyłączony.

## 2026-10-13 — zakładka ustawień i dołączone kamery testowe

Dodano „Ustawienia kamer” pod bazą danych: właściwości, tryby USB, indywidualne czasy tur oraz trwały checkbox pracy naprzemiennej. Odznaczenie uruchamia równoczesne pobieranie. Zmiana trybu zwalnia stare strumienie USB przed ich ponownym otwarciem, działa również z mostkiem Windows i nie restartuje kamer IP/testowych. Podgląd HTTP odnajduje nowego pracownika po zmianie trybu. Minimalny czas tury jest dostosowany do bieżących pomiarów analizy.

Przycisk dodawania jest na górze menu. Stan serwera jest osobną rozwijaną pozycją na dole, z mniejszą czcionką metryk. W dodawaniu dostępny jest typ „Kamera testowa” z wyborem Car Park lub Parking Garage. Do repozytorium i obrazu dołączono licencjonowane kopie UVG-VCM: 1920×1080/60 FPS, 40 s oraz 19 s, łącznie około 29 MB. Car Park spowolniono 4×, powtarzając klatki. Wyniki pozostają w bazie testowej; integracja eksportuje wyłącznie prawdziwy parking.

Weryfikacja: 37 testów automatycznych, pełne dekodowanie obu filmów bez błędów, weryfikacja parametrów FFprobe, zbudowany Docker oraz odizolowana próba przeglądarką z dwoma różnymi nagraniami. Potwierdzono dodawanie bez USB, checkbox i jego trwałość po restarcie, brak strumieni w ustawieniach/bazie, pomiary Full HD/60 FPS, rozwijany serwer, układ mobilny i brak błędów JavaScript. Produkcyjnego parkingu na 10000 nie uruchamiano.

## 2026-10-13 — ustawienia wydajności i oszczędzanie CPU

Dodano trwałe ustawienia wydajności w zakładce ustawień kamer: limit FPS podglądu, maksymalna szerokość, jakość JPEG, kodowanie tylko dla widzów, wyłączenie podglądu, limit OCR na kamerę, liczba wątków analizy i pauza OCR. Trzy profile uzupełniają formularz do ręcznego zapisu. Domyślny profil oszczędny: 5 FPS/maks. 640 px/JPEG 55, do 2 analiz OCR/s na kamerę, jeden wątek. Podgląd nie zmienia rozdzielczości klatki OCR ani wymogu trzech zgodnych odczytów.

JPEG jest kodowany raz na kamerę i współdzielony przez widzów. Generator strumienia zwalnia licznik widzów po odłączeniu i przenosi go po odtworzeniu pracownika. Przejście do bazy/ustawień zatrzymuje kodowanie, gdy nie ma innych klientów. Pauza OCR zatrzymuje nowe potwierdzenia; zmiany samego podglądu zachowują głosy. Zmiana wątków przeładowuje modele bez restartu kamer. Stan serwera pokazuje CPU aplikacji oddzielnie od całej maszyny; właściwości obejmują koszt kodowania, FPS i widzów. Formularz czeka na wczytanie opcji, zapobiegając nadpisywaniu zmian użytkownika.

Weryfikacja: 42 testy automatyczne. Zbudowano obraz i przeprowadzono odizolowaną próbę Dockera z dwoma rzeczywistymi filmami, panelu desktop/mobilnego, parametrów JPEG/FPS, pauzy OCR, wyłączenia podglądu, zatrzymania licznika JPEG bez widzów, trwałości po restarcie i przeładowania modeli z nową liczbą wątków. Limit OCR jest maksimum uruchomień, nie gwarancją szybkości ani procentowym limitem CPU. Dekodowanie źródła nadal zależy od parametrów kamer. Produkcyjnych usług nie zmieniano.
