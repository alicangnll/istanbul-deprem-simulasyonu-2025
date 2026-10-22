# 🌍 İstanbul Deprem Simülasyonu & Risk Analiz Haritası

İBB'nin (İstanbul Büyükşehir Belediyesi) **7.5 Mw büyüklüğündeki gece depremi senaryosuna** göre hazırlanmış analiz sonuçlarını, mahalle bazında interaktif bir harita üzerinde görselleştiren tek sayfalık web uygulaması.

🔗 **Canlı Demo:** [alicangnll.github.io/deprem-simulasyonu](https://alicangnll.github.io/deprem-simulasyonu/)

📊 **Kapsam:** 39 ilçe, 959 mahalle — can kaybı, yaralı, bina hasarı, altyapı hasarı ve geçici barınma tahminleri.

---

## ✨ Özellikler

- **Mahalle bazlı risk analizi** — Can kaybı ve ağır hasarlı bina sayısına göre 4 risk seviyesi (Kritik / Yüksek / Orta / Düşük); renk ve boyut kodlu işaretçiler
- **Detaylı mahalle kartları** — Her mahalle için can kaybı, yaralı sayıları (ağır/hastanede/hafif), bina hasar dağılımı (çok ağır → hafif), doğalgaz / içme suyu / atık su boru hasarları ve geçici barınma ihtiyacı
- **İlçe filtresi** — 39 ilçeden seçim yapınca harita otomatik odaklanır ve alt istatistik çubuğu o ilçenin toplamlarına güncellenir
- **Fay hattı katmanı** — Tek tuşla açılıp kapanan, GEM Global Active Faults veritabanından alınan 482 aktif fay hattı (tembel yükleme ile, sadece istendiğinde indirilir)
- **4 harita altlığı** — ArcGIS Sokak (varsayılan), OpenStreetMap, Esri Uydu, Esri Topografik — API anahtarı gerektirmez
- **Performans odaklı** — Marker clustering (yakın işaretçiler kümelenir), tek seferde toplu marker ekleme, O(1) eşleştirme için `Map` tabanlı veri yapısı, koordinat tekilleştirme
- **Modern arayüz** — Koyu tema, glassmorphism paneller, mobil uyumlu tasarım, yükleme ekranı

## 🛠️ Teknolojiler

| Bileşen | Açıklama |
|---|---|
| HTML / CSS / JavaScript | Tek dosya (`index.html`), derleme adımı yok |
| [Leaflet](https://leafletjs.com/) | Harita kütüphanesi (yerelde barındırılır) |
| [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) | İşaretçi kümeleme (yerelde barındırılır) |
| Font Awesome + Google Fonts | İkonlar ve tipografi (CDN) |
| GitHub Actions + Pages | Otomatik dağıtım |

## 📁 Veri Dosyaları

| Dosya | İçerik |
|---|---|
| `deprem.json` | İBB deprem senaryosu analiz sonuçları (959 mahalle kaydı) |
| `ilce.json` | Mahalle koordinatları (enlem/boylam) |
| `fay_hatlari_turkiye.geojson` | GEM Global Active Faults — Türkiye aktif fay hatları |

## 🚀 Yerelde Çalıştırma

Uygulama verileri `fetch` ile okuduğundan doğrudan `index.html` dosyasını açmak yerine basit bir web sunucusu üzerinden çalıştırmanız gerekir:

```bash
# Python ile (proje kök dizininde)
python3 -m http.server 8080
```

Ardından tarayıcıda `http://localhost:8080` adresini açın. Alternatifler: NGINX, Apache, IIS veya VS Code **Live Server** eklentisi.

## 📦 Dağıtım

`main` dalına yapılan her itme, `.github/workflows/static.yml` içindeki GitHub Actions iş akışı ile otomatik olarak GitHub Pages üzerine dağıtılır.

## 📚 Veri Kaynağı

- [İBB — Deprem Senaryosu Analiz Sonuçları](https://data.ibb.gov.tr/dataset/deprem-senaryosu-analiz-sonuclari/resource/9c3ac492-de4b-4245-b418-7ad3df67a193) (7.5 Mw gece senaryosu)
- [GEM Global Active Faults Database](https://github.com/GEMScienceTools/gem-global-active-faults) (fay hatları)

## ⚠️ Notlar

- Veri bir senaryo **tahminidir**, gerçek deprem sonuçlarını ifade etmez.
- 959 mahallelik veri yoğunluğu nedeniyle düşük donanımlı cihazlarda harita geç yüklenebilir; işaretçi kümeleme bu yükü azaltmak için kullanılmaktadır.

## 👤 Yazar

**Ali Can Gönüllü** — [GitHub](https://github.com/alicangnll)
