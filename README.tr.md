# SiliconNet

[English](README.md) · **Türkçe** · [Deutsch](README.de.md)

macOS için yerel DPI atlatma proxy'si. Kendi Mac'inizde çalışır, `127.0.0.1`
adresini dinler ve tanımladığınız siteleri, TLS ClientHello paketini parçalayan
yerel bir proxy üzerinden yönlendirir — böylece aradaki paket inceleme
(DPI) donanımı sunucu adını okuyup bağlantıyı kesemez.

![macOS 12+](https://img.shields.io/badge/macOS-12%2B-black)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![License MIT](https://img.shields.io/badge/License-MIT-green)

## Ne işe yarar

Bazı ağlar siteleri, TLS el sıkışmasındaki `SNI` alanına bakarak engeller — bu,
tarayıcınızın şifreleme başlamadan önce açık metin olarak gönderdiği sunucu
adıdır. Ad bir engel listesiyle eşleşince bağlantı sıfırlanır. Aynı ağlar
genellikle DNS'i de zehirler; domain gerçek sunucu yerine bir engel sayfasına
çözümlenir.

SiliconNet ikisini birden ele alır:

- **DNS over HTTPS.** Tanımlı domainler şifreli bir DoH çözümleyicisi üzerinden
  çözülür, bu yüzden zehirlenmiş yerel DNS yanıtı hiç kullanılmaz.
- **TLS kayıt parçalama.** ClientHello iki ayrı TLS kaydına bölünür; tek kayda
  bakan bir DPI kutusu sunucu adının tamamını göremez. Yirmi beş strateji
  mevcuttur; motor sizin ağınızda hangisinin çalıştığını ölçer ve onu kullanır.

Yalnızca listelediğiniz siteler proxy'den geçer. Geri kalan her şey normal
şekilde bağlanır.

**Bu bir VPN veya anonimlik aracı değildir.** IP adresinizi gizlemez; ziyaret
ettiğiniz site yine gerçek adresinizi görür. Yalnızca bağlantının *nasıl
açıldığını* değiştirir, böylece aradaki filtre onu sınıflandıramaz. Yalnızca
izniniz olan yerlerde kullanın.

## Gereksinimler

| | |
|---|---|
| İşletim sistemi | macOS 12 Monterey veya üzeri — **yalnızca macOS**, Windows/Linux sürümü yok |
| Python | 3.10+ (Homebrew, python.org veya Command Line Tools) |
| Yetki | Yönetici hesabında gerekmez; standart hesapta macOS bir kez parola sorar |

Başlatıcı, Python paketlerini (`pystray`, `Pillow`, PyObjC) yerel bir sanal
ortama kurar. Sisteme hiçbir şey kurulmaz, servis eklenmez ve hiçbir şey root
olarak çalışmaz.

## Kurulum

```bash
git clone https://github.com/erkmenboz/siliconnet.git
cd siliconnet
./siliconnet-launcher.sh
```

Finder'dan **`SiliconNet.command`** dosyasına çift tıklayarak da açabilirsiniz;
Terminal açılır ve aynı başlatıcıyı çalıştırır.

İlk çalıştırmada `.venv` oluşturulur ve gereksinimler kurulur. `python3 -m venv`
başarısız olursa Command Line Tools'u kurun:

```bash
xcode-select --install
```

Klonlamak yerine hazır arşiv indirdiyseniz macOS onu karantinaya alabilir:

```bash
xattr -dr com.apple.quarantine siliconnet-macos-<sürüm>
```

## Kullanım

Çalışmaya başladığında:

- **Menü çubuğu simgesi** sağ üstte, Wi-Fi ve saatin yanında belirir. Tek
  tıklamayla menü açılır — durum, ping, panel, yeniden başlat, çıkış.
- **Panel** şu adrestedir: **<http://127.0.0.1:8888>**

Panelden yönlendirmek istediğiniz domainleri ekleyebilir, hangi stratejinin
kazandığını izleyebilir, dili (EN/TR/DE) ve görünümü (açık/koyu)
değiştirebilirsiniz.

**Bilgisayar açıldığında otomatik başlaması için:** panel → **Ayarlar** →
**Otomatik Başlat**. Bu, `~/Library/LaunchAgents` altına kullanıcı seviyesinde
bir LaunchAgent kurar. Sonrasında proje klasörünü taşımayın — servis tam yolu
kaydeder.

**Durdurmak için:** menü çubuğu → **Exit**. Terminal penceresini kapatmak
yeterli değildir; çıkarken sistem proxy ayarlarınızın geri yüklenmesi gerekir.

## Nasıl çalışır

SiliconNet, etkin her ağ servisinin HTTP ve HTTPS proxy ayarını macOS'un kendi
`networksetup` aracıyla yazar, önceki değerleri `macos_proxy_state.json`
dosyasına yedekler ve durduğunda geri yükler.

Çoğu kişisel Mac'te oturum açan kullanıcı yöneticidir ve `networksetup`
değişikliği parolasız uygular. macOS reddederse — standart hesap ya da
"ayarları değiştirmek için yönetici parolası iste" seçeneği — aynı komut kümesi
bir kez `osascript … with administrator privileges` üzerinden tekrarlanır ve
sistemin kendi parola penceresi görünür. İptal ederseniz ayarlarınıza
dokunulmaz.

Bazı uygulamalar kendi HTTP yığınlarını gömer ve macOS proxy ayarını tamamen
yok sayar (Discord'un güncelleyicisi tipik örnektir). SiliconNet proxy'yi
yönetirken `HTTP_PROXY`/`HTTPS_PROXY` değişkenlerini launchd oturumuna da
yayınlar, böylece sonradan açılan uygulamalar proxy'ye ulaşabilir. Çıkışta
ikisi de geri alınır.

### Verileriniz nerede

```text
~/Library/Application Support/SiliconNet
```

| Dosya | Amaç |
|---|---|
| `config.json` | Siteler, portlar, gizlilik ve performans ayarları |
| `bypass.log` | Uyarı/hata günlüğü (ayrıntı için `DPI_BYPASS_LOG_LEVEL=INFO`) |
| `macos_proxy_state.json` | Önceki proxy durumunuz, çıkışta geri yüklenir |
| `strategy_cache.json` | Hangi site için hangi strateji çalışıyor |
| `ai_strategy.json` | Uyarlanabilir strateji öğrenme verisi |
| `stats.json` | Çalışma sayaçları |

LaunchAgent günlükleri `~/Library/Logs/SiliconNet/` altına yazılır. Hiçbir veri
dışarı gönderilmez; hepsi Mac'inizde kalır. Bkz. [PRIVACY.md](PRIVACY.md).

## Sorun giderme

**SiliconNet beklenmedik şekilde kapandıktan sonra internet yok.** Sistem
proxy'niz hâlâ hiçbir şeyin dinlemediği bir porta işaret ediyor olabilir.
SiliconNet'i tekrar başlatın — açılışta bu durumu algılayıp temizler — ya da
proxy'yi elle kapatın:

```bash
networksetup -setwebproxystate Wi-Fi off
networksetup -setsecurewebproxystate Wi-Fi off
```

**Bir site hâlâ açılmıyor.** Proxy etkinleşmeden *önce* başlatılmış uygulamalar
ayarı almamış olabilir; uygulamayı kapatıp yeniden açın. Tarayıcılar proxy
ayarını açılışta okur, bu yüzden pencereyi kapatmak yerine tarayıcıdan tamamen
çıkın (⌘Q).

**Menü çubuğu simgesi yok.** Simge için `pystray`, `Pillow` ve PyObjC gerekir;
bunları başlatıcı `.venv` içine kurar. Uygulamayı farklı bir Python
yorumlayıcısıyla başlatırsanız simge atlanır, geri kalan her şey çalışmaya
devam eder. Çentikli bir MacBook'ta kalabalık bir menü çubuğu da simgeyi
görünmez kılabilir — panel yine yukarıdaki adresten erişilebilir.

**Ne yaptığını görmek için:** `DPI_BYPASS_LOG_LEVEL=INFO ./siliconnet-launcher.sh`
ile başlatın veya panelde **Loglar** sekmesini açın.

## Derleme ve doğrulama

```bash
./run_tests.sh                      # test paketi
scripts/build_macos_release.sh      # dist/ altına temiz arşiv
scripts/verify_macos_release.sh     # testler + paketleme kontrolleri
```

## Katkılar ve lisans

SiliconNet MIT lisanslıdır.

Proxy çekirdeği, strateji motoru ve paneli CleanNet'ten (MIT, Telif hakkı ©
2026 digaxie) türetilmiştir. Orijinal telif bildirimi [LICENSE](LICENSE)
dosyasında korunur; hangi bölümün nereden geldiği [NOTICE](NOTICE) dosyasında
ayrıntılıdır.

macOS entegrasyon katmanı bu proje için yazılmıştır: `networksetup` ile proxy
yönetimi, LaunchAgent ile otomatik başlatma, `lsof` tabanlı akış çözümleyici,
menü çubuğu öğesi ve ortam değişkeni uyumluluk katmanı.
