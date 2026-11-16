# YALW — Yet Another Live Widget

[English](README.md) · **Türkçe**

Linux için canlı widget. Bir şey olduğunda ekranın istediğin köşesinde kısa süreliğine
bir kart belirir, sonra kaybolur:

| Durum | Kart |
|---|---|
| Yeni şarkı | Kapak, başlık, sanatçı, ilerleme çubuğu |
| Sonraki / önceki şarkı | Aynı kart, metin yöne göre kayar, yön rozeti çıkar |
| Çal / duraklat | Kapak solar/canlanır, rozet belirir |
| Bluetooth cihaz bağlandı / koptu | Cihaz türüne göre ikon, ad, pil halkası (şarj oluyorsa ⚡); kopunca gri kart |
| Şarj aleti takıldı (isteğe bağlı: çıkarıldı) | Kutusuz, yazısız, şeffaf: 0'dan pil seviyesine dolan büyük bir halka, içinde şarj ikonu ve onunla birlikte artan sayı; yukarıdan ya da yandan kayarak gelmez, ayarlardaki kart konumunda olduğu yerde belirir; çıkarılınca kalan süreyle "Pilde çalışıyor" |
| **Eklentilerin kartları** | Herkes kendi olayını yazabilir; aşağıda [Eklentiler](#eklentiler) |
| **Şarkı sözleri** (varsayılan kapalı) | Nakarat gelince kart yukarıdan iner; kelime senkronluysa her kelime söylenirken yumuşakça belirir (fade), değilse satır bir bütün olarak belirir |

Karta fare ile gelince kapanma durur ve **önceki / çal-duraklat / sonraki** düğmeleri
animasyonla çıkar. Ama hiçbir şey kartı sonsuza kadar açık tutmaz: fare
4 saniye kıpırdamazsa (ya da sağ tık şeridi 4 saniye kullanılmazsa) kart kapanır; fareyi oynatmak ya da bir düğmeye basmak süreyi
sıfırlar. Dokunulmayan söz kartı ise nakarat boyunca açık kalır, uzun tutulan bir dize ya da satır arası boşluk onu kapatıp açmaz; yalnızca nakaratın sonu
(ya da azami süre) kapatır. Fare üstündeyken ve kıpırdamıyorsa 4 saniye kuralı yine geçerlidir. Hiç dokunulmayan normal kartlar kendi süresini (Config → Olaylar) yaşar.

* **İmleç kartın çıkacağı yerdeyse kart çıkmaz.** Kart açılırken pencere önce görünmez haliyle belirir, 0,1 sn içinde imlecin
  kartın dikdörtgeninde olup olmadığına bakılır; oradaysa kart hiç görünmeden geri çekilir (işaret ettiğin şeyin üstünü kapatmaz).
* **Açılan kart en az 3 saniye açık kalır.** Süresi dolsa, nakarat bitse ya da oynatıcı gitse bile kapanma isteği 3. saniyeye
  ertelenir; bu sırada yeni bir kart gelirse bekleyen kapanma iptal olur, böylece kart kapanıp açılmaz. Kapanma yine eylemin
  bitişine bağlıdır (nakaratın sonu, Config'teki azami süre); yalnızca çift tık ("hızla kapat") 3 saniyeyi beklemez. İlerleme çubuğuna tıklayıp sürükleyerek ileri-geri sarabilirsin.

* **Çift tık** (kartın boş bir yerine): kart hızla solarak kapanır.
* **Sağ tık**: kartın üstüne küçük bir eylem şeridi açılır, ikinci sağ tık ya da bir boşluğa tık kapatır.
  Oynatıcıyı aç · sözleri 0,5 sn erken · 0,5 sn geç · **yanlış söz: bu şarkı için gizle** (tekrar basınca geri gelir) ·
  tüm kartları sustur. Söz zamanlaması ve gizleme **şarkıya özel** hatırlanır (`~/.local/state/yalw/songs.json`).

## Hangi masaüstünde nasıl çalışır

Başlangıçta Wayland derleyicisinin `wlr-layer-shell` sunup sunmadığı yoklanır:

* **layer-shell** — KDE Plasma, Hyprland, sway, niri, COSMIC, labwc… Kenara sabitlenmiş gerçek bir overlay yüzeyi.
* **xcb** — X11 oturumları ve layer-shell'i olmayan Wayland derleyicileri (**GNOME**): XWayland üzerinde, her şeyin üstünde duran pencere.
* **wayland** — son çare: sıradan Wayland penceresi (konumu derleyici belirler).

`python -m yalw doctor` hangisinin seçileceğini gösterir.

## Gereksinimler

`python` ≥ 3.11, `PySide6`, `dbus-fast`, `bluez`, `upower` (isteğe bağlı: şarj durumu), `PyYAML` (isteğe bağlı: LRCLIB'in kelime senkronlu `lyricsfile` biçimi).
layer-shell için `layer-shell-qt`.

```bash
# Arch
sudo pacman -S pyside6 python-dbus-fast layer-shell-qt bluez upower
pipx install --system-site-packages .   # sistem paketlerini kullanır (Arch pip install'ı doğrudan engeller)

# Debian / Ubuntu / Fedora ve diğerleri (PySide6 pip'ten gelir; sistem paketi gerekmez)
sudo apt install pipx bluez upower        # Fedora: sudo dnf install pipx bluez upower
pipx install .                             # `yalw` komutunu kendi ortamında kurar (PyYAML'li söz desteği: pipx install ".[lyrics]")
```

Ya da tek komutla (root gerekmez; YALW kendi sanal ortamına kurulur, `yalw` komutu `~/.local/bin`'e bağlanır, menüye ve girişte başlatmaya eklenir):

```bash
./install.sh                # kur / güncelle (girişte başlatmadan: ./install.sh --no-service)
./uninstall.sh              # kaldır; ayarların, eklentilerin ve önbellek kalır
./uninstall.sh --purge      # hepsini sil (önce sorar; --yes sormaz)
```

Kurulumdan sonra: `yalw doctor` (hangi görüntü yolu seçilecek), `yalw demo all` (kartları dene), `yalw install` (girişte başlat).
GNOME'da ek bir şey gerekmez (XWayland yeterli); KDE Plasma ve Hyprland gibi derleyicilerde `layer-shell-qt` paketi varsa kart
gerçek bir overlay olarak açılır.

## Kullanım

```bash
./bin/yalw run                  # başlat
./bin/yalw demo all             # örnek olayları sırayla göster
./bin/yalw demo bluetooth-low   # tek bir örnek (yardım için: yalw demo -h)
./bin/yalw config               # YALW Config: ayar penceresi (menüde de var)
./bin/yalw reload               # ayar dosyasını elle düzenlediysen daemon'u yenile
./bin/yalw quiet on|off|toggle  # sunum/oyun sırasında tüm kartları sustur
./bin/yalw install              # girişte otomatik başlat (systemd servisi; yoksa XDG autostart)
./bin/yalw uninstall
```

`pip install .` sonrası `./bin/yalw` yerine doğrudan `yalw` yazman yeter.
Ayar değiştirince: `systemctl --user restart yalw`

Demo türleri: `new next prev pause play bluetooth bluetooth-low bluetooth-charging bluetooth-keyboard bluetooth-speaker bluetooth-off lyrics lyrics-words`

## Şarkı sözleri

`yalw config` → **Sözler** sekmesinden aç (varsayılan kapalı). İki mod: **sadece nakarat** (nakarat
gelince kart iner, bitince çekilir) ya da **tüm şarkı**. Sözler çalma konumuna göre akar; pause'da kart çekilir,
ileri sarınca doğru yere atlar.

**Kart ne zaman çıkar:** Söz kaynağı nakaratı **kendisi işaretlediyse** (Apple/boidu: `Chorus`; başka kaynaktan gelen sözlere
de aktarılır, aynı kayıt olduğu için zamanlar tutar) kart yalnızca nakarat boyunca durur. Nakarat işaretli değilse (ve aşağıdaki
deneysel tahmin kapalıysa ya da hiçbir satır tekrar etmediği için bir şey bulamadıysa) kart o şarkıda **tüm şarkı boyunca** durur:
sözü bulunmuş bir şarkı kartsız kalmaz. Durum sayfası kaç nakarat bölümü bulunduğunu ya da "nakarat etiketi yok: tüm şarkı"
yazar; hiç söz bulunamazsa günlükte `lyrics: none found for ...` satırı çıkar (ulaşılamayan kaynaklar varsa adlarıyla).

### Deneysel: nakaratı tahmin et

**Sözler → Deneysel → Nakaratı tahmin et** (varsayılan kapalı). Açıksa, etiketi olmayan şarkılarda tüm şarkı yerine nakarat sözün
kendisinden aranır (hiçbir şey tekrar etmiyorsa yine tüm şarkı), en güvenilirden en zayıfa:

1. Bölüm sınırları biliniyorsa **bölümler bütün olarak** karşılaştırılır: en çok geri gelen bölüm nakarattır
   (eşitlikte gürlük, sonra şarkı adını geçen, sonra uzun olan). Sınırlar Apple'ın `<div>`lerinden, LRC'deki boş
   satırlardan ve LRCLIB'in düz metnindeki kıta boşluklarından alınır.
2. Hiç sınır yoksa tekrar eden satır blokları (en zayıfı: ön-nakaratı yapıştırabilir). Birbirinden farklı iki
   bölük eşit sayıda tekrar ediyorsa yine gürlük belirler.

Apple'ın etiketlerini doğruluk olarak kullanıp 24 şarkıda ölçtüm (etiketler gizlenerek): bölüm tabanlı yöntem
67 nakaratın **53'ünü** doğru yerde buldu (eski satır tabanlı: 34); LRCLIB'de 21'den **48**'e çıktı.
Kalan hatalar çoğunlukla "bölüm tekrar ediyor ama nakarat değil" (ör. köprü) türünden; söz metninden bunu kesin
ayırmanın yolu yok. Tahmin yanılabilir; o yüzden deneysel. Sözler yalnızca zamanlıysa gösterilir; düz metin gösterilmez.

**Nakarat öğrenme (ses), tahminin parçası:** Gürlük, tahmini düzeltmek için kullanılır ve yalnızca "Nakaratı tahmin et"
açıkken çalışır. Bir şarkıyı ilk kez çaldığında YALW, o oynatıcının
kendi ses akışını dinler (PulseAudio/PipeWire `sink-input`; yalnızca o oynatıcı, akış kesin bulunamazsa hiç dinlemez),
**saniye başına tek bir gürlük sayısı** çıkarır ve sesi hemen atar. Sayılar şarkı çalarken bellekte durur, şarkı bitince
`~/.local/state/yalw/audio` altına yazılır (şarkı başına birkaç KB). O şarkı bir daha dinlenmez; yarım dinlenmişse
(ortadan başladıysan) sonraki çalışta tamamlanır. Ham ses hiç saklanmaz ve hiçbir şey bilgisayardan çıkmaz.
Gürlük yalnızca eşitlikte belirleyicidir ve bir bölümün gürlüğü, o bölümün saniyelerinin en az yarısı dinlenmişse
kullanılır (yarım dinlenmiş şarkı da işe yarar). Etiket varsa etikete bakılır, gürlüğe değil. Ayar: **Sözler → Deneysel**
("Hepsini unut" öğrenilenleri siler). Ayrıca `pactl` ve `parec` gerekir (PipeWire/PulseAudio'da hazır gelir).
Sözü nakarat etiketli şarkılar **hiç dinlenmez** (etiket varsa gürlüğe bakılmaz); dinleme başlamışken etiket sonradan gelirse o şarkının sayıları atılır.

Oynatma konumu, özellik açıkken 4 saniyede bir yeniden okunur (oynatıcılar kayabilir, ileri sarma her zaman haber verilmez).
En iyi kaynak zaman aşımına uğrarsa elde edilen sonuç gösterilir ama **saklanmaz**, bir sonraki çalışta tekrar denenir.

| Kaynak | Ne verir |
|---|---|
| Oynatıcının kendi sözü / yerel `.lrc` | Şarkının yanındaki `.lrc` ya da `~/.cache/yalw/local/Sanatçı - Şarkı.lrc`; her şeyden önce gelir |
| Apple Music, [lrc.red](https://lrc.red) vekili üzerinden | Kelime senkronlu, bölüm etiketli |
| [LRCLIB](https://lrclib.net) | Satır senkronlu (bazen kelime) |
| boidu (`lyrics-api.boidu.dev`) | Apple Music'in ikinci vekili |

Hepsi paralel sorgulanır; **gerçek kelime senkronu > yapay kelime senkronu > satır senkronu** sırasıyla en
iyisi seçilir. Bulunanlar `~/.cache/yalw/lyrics` altında saklanır, bulunamayanlar 3 gün hatırlanır (ağ hatası hatırlanmaz).

> **Gizlilik ve şartlar:** Özellik açıkken çalan şarkının sanatçı, ad, albüm ve süresi bu servislere gönderilir;
> kapalıyken hiçbir şey gönderilmez. lrc.red ve boidu Apple Music sözlerini sunan, Apple'ın onaylamadığı topluluk
> vekilleridir; kullanmak senin tercihin. İstemediğin kaynağı sekmeden kapatabilirsin. YALW sözleri dağıtmaz,
> çalışma anında alıp gösterir.

Denemek için: `yalw demo lyrics-words` (kelime kelime) ya da `yalw demo lyrics` (satır satır). Demo şarkısı her yerde aynıdır
(Never Gonna Give You Up · Rick Astley); ad yalnızca bir etikettir, gösterilen sözler YALW için uydurulmuş örnek metindir.

## Eklentiler

Yeni bir olay (VPN bağlandı, derleme bitti, indirme tamamlandı…) eklemek için kod yazmak yeter; kartı YALW çizer.
İki yol, ikisi de aynı karta çıkar:

```sh
yalw notify "Yedekleme bitti" "2,4 GB · 38 sn" --icon circle-check          # herhangi bir betikten
yalw notify "İndiriliyor" "ubuntu.iso" --icon download --progress 42 --key dl   # halka; aynı key kartı günceller

yalw extension new kahve      # ~/.local/share/yalw/extensions/kahve.py: çalışan bir şablon
yalw extension enable kahve   # ya da YALW Config → Eklentiler
yalw extensions               # neler kurulu, hangisi çalışıyor
```

Python eklentisi `async def run(yalw)` yazar ve bir şey olunca `yalw.notify(...)` der; D-Bus sinyali, dosya, zamanlayıcı,
ne izlerse. Kart alanları: başlık, alt başlık, ikon (YALW'ın 178 Lucide ikonundan biri), renk, halka (`progress`), halka içi
değer, rozet, süre, `key`. Her şey kısaltılır ve temizlenir; hız sınırı dakikada 12 kart; sessiz mod eklenti kartlarını da susturur.

**Güven:** eklenti, senin yetkilerinle çalışan bir Python programıdır, korumalı alanda değildir. Bu yüzden YALW hiçbir eklentiyi
kendiliğinden açmaz (klasöre atmak yetmez, **Eklentiler** sekmesinden ya da `yalw extension enable` ile açılır), keşif sırasında
kodu çalıştırmaz (adı ve açıklamayı `ast` ile okur) ve her eklenti kendi iş parçacığında çalışır: takılan ya da çöken eklenti
medya izlemeyi ve diğerlerini durdurmaz (çökerse 2, 6, 20 sn sonra yeniden denenir, sonra durdurulur; sebep Config'te yazar).

**Canlı widget:** `yalw.live(anahtar, ...)` kalıcı bir kart açar; aynı anahtarla her çağrı kartı yerinde günceller (işlemci
yükü, indirme, sayaç). Kendiliğinden kapanmaz; `yalw.clear(anahtar)`, eklentinin durması, Sessiz mod ya da çift tık kapatır
(çift tıkla kapatılan, sahibi `clear` edip yeniden başlatana kadar geri gelmez). Ekranda aynı anda tek kart durur: başka bir kart
(şarkı, Bluetooth, bildirim) kendi süresince öne geçer, sonra canlı kart geri gelir. Betikten: `yalw notify "" --progress 40
--key build --live`, bitince `yalw notify --clear build`.

Şarj kartı da bu API'yle yazılmış yerleşik bir eklentidir (`yalw/builtin/power.py`). Ayrıntılı rehber (İngilizce, topluluk için):
[docs/EXTENSIONS.md](docs/EXTENSIONS.md); üç örnek: `examples/extensions/` (`cpu_load.py` canlı bir halka örneği).

## YALW Config

Küçük, tek pencerelik ayar uygulaması (`yalw config`; `yalw install` sonrası uygulama menüsünde
**YALW Config** olarak görünür). Dil: Türkçe, English, Deutsch, Español ya da otomatik. Hem kartlar
hem Config aynı dili kullanır.

* **Genel** — konumu mini ekrandan seç, kenar boşluğu, monitör, gösterim modu
* **Görünüm** — **kompakt mod** (kartlar daha geniş ve alçak: müzik 480×104, sözler 480×120), boyut (%70–160), köşe yuvarlaklığı, vurgu rengi (kapaktan ya da sabit), kapak karartma,
  Bluetooth rengi, gölge, ekolayzır, ilerleme çubuğu, hover düğmeleri, az hareket, yazı tipi
* **Olaylar** — hangi olayların kart açacağı (şarja takma / çıkarma dahil), kartların kalma süresi, yok sayılacak oynatıcılar
* **Bluetooth** — pil halkası, kırmızı/sarı eşikleri
* **Eklentiler** — kurulu eklentiler, aç/kapa, durumları, klasörü aç
* **Sözler** — aç/kapa, mod, kaynaklar
* **Durum** — çalışıyor mu, sürüm, çalan şarkı, hangi söz kaynağı yanıt veriyor, sessiz mod anahtarı, **günlük** (kopyalanabilir) ve Başlat/Yeniden başlat

Başlıktaki **Çalışıyor / Durdu** göstergesi her sekmeden görünür; tıklayınca Durum sayfasına gider.
Günlük ayrıca `~/.local/state/yalw/yalw.log` dosyasında durur (Qt/QML uyarıları dahil, 400 KB'ı geçmez).

Pencerenin üstünde **canlı bir önizleme kartı** durur: kartların kendisi, ayarlar o an neyse öyle çizilir
(kompakt mod, köşeler, vurgu, gölge, Bluetooth eşikleri, kelime kelime söz…). Açık sayfaya göre kendisi
şarkı, söz ya da Bluetooth kartına geçer; istersen altındaki düğmeyle sen seçersin. Üstüne gelince
hover düğmeleri çıkar, Bluetooth kartına tıklayınca başka bir cihaz örneği gelir. Şarkı ve söz önizlemesi **en son çalan şarkıdır** (kapak, ad, renk; sözler de YALW'ın o şarkı için zaten bulduğu sözlerdir ve nakaratından başlayarak
kelime kelime akar). O şarkının sözü yoksa kartta "Sözler buraya gelecek" yazar; hiç şarkı çalmadıysa demo şarkısı gösterilir. Boyut (%) ve yazı tipi
önizlemeye yansımaz; onlar ekrandaki gerçek kartta görünür.

Düğme yok: **her değişiklik kısa bir duraklamadan sonra kendiliğinden kaydedilir** ve çalışan daemon'a
uygulanır (daemon aynı süreçte yeniden başlar). Konumu, kenar boşluğunu, monitörü, gösterim modunu ya
da boyutu değiştirdiysen gerçek ekranda bir örnek kart da çıkar. Sağ alttaki **Varsayılana dön** iki
tıklamayla çalışır (ilkinde "Emin misin?" der).

Config'in vurgu rengi, çalan şarkının kapak rengidir (şarkı yoksa amber).

## Ayar dosyası

`~/.config/yalw/config.toml` — her anahtarın açıklaması dosyanın içinde. Elle düzenleyebilirsin,
ardından `yalw reload`. Geçersiz değerler varsayılana döner, aralık dışı sayılar kırpılır.

Örnek: tarayıcı sekmeleri kart açmasın → `[media] ignore = ["firefox"]`

Hyprland'da bulanıklık gibi kuralları `yalw` ad alanına verebilirsin:
`layerrule = blur, yalw`

## Notlar

* Cihaz türü BlueZ'in `Icon` alanından (ve addan) çıkarılır; ikonlar [Lucide](https://lucide.dev) (ISC).
* BlueZ şarj *durumunu* bildirmez; ⚡ yalnızca UPower o cihaz için "şarj oluyor" diyorsa görünür.
* Önceki/sonraki ayrımı MPRIS'te yoktur; kartın kendi düğmeleri kesin bilinir, medya tuşları için
  şarkı geçmişinden ve konumdan çıkarım yapılır.
* Kapaklar `~/.cache/yalw/art` altında önbelleğe alınır (en çok 64 MB; eskiler silinir).
* Kapak adresini oynatıcı verir; YALW yalnızca o adresi indirir.
* Testler: `QT_QPA_PLATFORM=offscreen python -m pytest` (280 test: şema, çeviriler, olay sınıflandırma, söz arama/nakarat, şarkıya özel tercihler, Config modeli)
* Lisans: GPL-3.0 veya sonrası (`LICENSE`). Paketlenen Lucide ikonları ISC lisanslıdır (`yalw/assets/lucide/LICENSE`).
