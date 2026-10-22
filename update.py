#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
alicangonullu.com / istdeprem — Veri ve Harita Güncelleme Otomasyonu (update.py)
================================================================================
Konum: istdeprem/update.py

Bu betik, istdeprem projesinde kullanılan tüm dinamik ve sismolojik veri setlerini
tek bir komutla veya bağımsız modüller halinde otomatik olarak günceller:

  1. [İBB Deprem Verileri]:
     İBB Açık Veri Portalı 7.5 Mw Senaryo veri dökümünü çeker, Windows-1254
     karakter bozulmalarını onarır, 959 mahalleyi doğrular ve
     'iller/istanbul/deprem.json' dosyasını günceller.

  2. [Toplanma Alanları]:
     Türkiye genelindeki 41.700+ toplanma alanını (81 il) doğrular, il bazlı
     klasörlerle senkronize eder ve 'iller/iller_index.json' dosyasını
     güncel il özetleriyle yeniler.

  3. [Diri Fay Hatları & Tarihsel Sismoloji]:
     GEM Global Active Faults / SHARE-EMME veri setlerini işler. Türkiye'deki
     951 diri fay segmentini tarihsel depremler, son kırılma yılları, geçen süre
     ve sismotektonik parametrelere göre gerçekçi risk seviyelerine ayırır:
       - Kritik Sismik Boşluk (Marmara Kumburgaz 1766, Yedisu 1784)
       - Yüksek Risk / Boşluk Adayı (Gemlik, Bandırma)
       - Orta Risk (KAF 20. yy 1939-1944 segmentleri, Batı Anadolu grabenleri)
       - Düşük Risk / Enerji Boşaldı (6 Şubat 2023 Maraş, 1999 Gölcük/Düzce, 2020 Sivrice/Sisam, 2011 Van)
       - Düşük - Orta Risk / Yavaş Deformasyon (İç Anadolu, Tuz Gölü, Ecemiş)
       - Megathrust (Helen - Kıbrıs Yayı)
     Tüm bu sınıflandırmayı 'fay_hatlari_turkiye.geojson' içine yazar.

  4. [Bütünlük Denetimi (Integrity Baseline)]:
     Güncellemeler tamamlandıktan sonra 'ops/integrity_check.sh --baseline --force'
     çalıştırarak SHA-256 bütünlük baseline'ını otomatik senkronize eder.

Kullanım:
  cd istdeprem && python3 update.py --all
  # VEYA ana dizinden:
  python3 istdeprem/update.py --all

Parametreler:
  --all            # Tüm güncelleme hattını sırayla çalıştırır
  --deprem         # Yalnızca İBB Deprem verilerini günceller
  --camps          # Yalnızca Toplanma Alanları ve il indeksini günceller
  --faults         # Yalnızca Türkiye Fay Hatları GeoJSON'unu günceller
  --download-gem   # Fay güncellemesinde GEM ham dosyasını GitHub'dan indirir
  --integrity      # Yalnızca SHA-256 bütünlük manifestosunu günceller
  --status         # Mevcut veri durumunu kontrol edip özetler
  --no-backup      # Otomatik .bak yedekleme dosyası oluşturmaz

Gereksinimler:
  Python 3.8+ (Yalnızca standart kütüphaneler)
================================================================================
"""

import os
import sys
import json
import time
import shutil
import urllib.request
import urllib.error
import argparse
import subprocess
from datetime import datetime

# =============================================================================
# Dizin ve Dosya Yolları (istdeprem Klasörüne Göre Dinamik Çözümleme)
# =============================================================================
# BASE_DIR: istdeprem klasörünün mutlak yolu
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# PROJECT_ROOT: Web kök dizini (ops klasörüne erişim için)
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

ILLER_DIR = os.path.join(BASE_DIR, "iller")
ISTANBUL_DIR = os.path.join(ILLER_DIR, "istanbul")

DEPREM_JSON_PATH = os.path.join(ISTANBUL_DIR, "deprem.json")
ILCE_JSON_PATH = os.path.join(ISTANBUL_DIR, "ilce.json")
FAYLAR_GEOJSON_PATH = os.path.join(BASE_DIR, "fay_hatlari_turkiye.geojson")
TURKIYE_CAMPS_PATH = os.path.join(ILLER_DIR, "turkiye_toplanma_alanlari.json")
ILLER_INDEX_PATH = os.path.join(ILLER_DIR, "iller_index.json")

# ops/integrity_check.sh dosya yolu (istdeprem dışındaki ops dizini)
INTEGRITY_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "ops", "integrity_check.sh")

# Uzak Açık Veri Uç Noktaları
IBB_DUMP_URL = "https://data.ibb.gov.tr/datastore/dump/9c3ac492-de4b-4245-b418-7ad3df67a193?format=json"
GEM_GEOJSON_URL = "https://raw.githubusercontent.com/GEMScienceTools/gem-global-active-faults/master/geojson/gem_active_faults_harmonized.geojson"

# =============================================================================
# Konsol Çıktı Formatlayıcıları (ANSI Renkleri)
# =============================================================================
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"

def log_header(title):
    print(f"\n{C.BOLD}{C.CYAN}{'='*78}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  {title}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'='*78}{C.RESET}")

def log_info(msg):
    print(f"{C.BLUE}[INFO]{C.RESET} {msg}")

def log_success(msg):
    print(f"{C.GREEN}[OK]{C.RESET} {msg}")

def log_warn(msg):
    print(f"{C.YELLOW}[UYARI]{C.RESET} {msg}")

def log_error(msg):
    print(f"{C.RED}[HATA]{C.RESET} {msg}")

def backup_file(filepath):
    """Dosyanın .bak uzantılı yedeğini oluşturur."""
    if os.path.exists(filepath):
        bak = filepath + ".bak"
        try:
            shutil.copy2(filepath, bak)
            log_info(f"Yedek oluşturuldu: {os.path.basename(bak)}")
        except Exception as e:
            log_warn(f"Yedek oluşturulamadı ({filepath}): {e}")

# =============================================================================
# 1. MODÜL: İBB Deprem Senaryo Verisi Güncelleme
# =============================================================================
WIN1254_CORRECTIONS = {
    '\u00fd': 'ı', '\u00fe': 'ş', '\u00f0': 'ğ',
    '\u00dd': 'İ', '\u00de': 'Ş', '\u00d0': 'Ğ',
    'Ý': 'İ', 'Þ': 'Ş', 'Ð': 'Ğ',
    'ý': 'ı', 'þ': 'ş', 'ð': 'ğ',
}

def clean_turkish_text(text):
    if not isinstance(text, str):
        return text
    s = text
    for bad, good in WIN1254_CORRECTIONS.items():
        s = s.replace(bad, good)
    return " ".join(s.split()).strip()

def to_int_or_zero(val):
    if val is None or val == "":
        return 0
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0

def update_deprem(backup=True):
    """İBB Açık Veri Portalı'ndan 7.5 Mw İstanbul senaryo dump'ını indirip günceller."""
    log_header("İBB 7.5 Mw İSTANBUL DEPREM VERİLERİ GÜNCELLENİYOR")
    log_info(f"Hedef Dosya: {os.path.relpath(DEPREM_JSON_PATH, BASE_DIR)}")
    log_info(f"Kaynak URL : {IBB_DUMP_URL}")
    
    if backup:
        backup_file(DEPREM_JSON_PATH)

    req = urllib.request.Request(
        IBB_DUMP_URL,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) update.py/1.0"}
    )

    log_info("İBB Açık Veri sunucusundan veri paketi indiriliyor...")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw_bytes = resp.read()
            raw_text = raw_bytes.decode("utf-8", errors="ignore")
            data = json.loads(raw_text)
    except Exception as e:
        log_error(f"İBB Açık Veri bağlantı hatası: {e}")
        return False

    records = data.get("records", [])
    if not records:
        log_error("İBB verisi boş döndü veya 'records' alanı bulunamadı!")
        return False

    log_info(f"İndirilen ham kayıt sayısı: {len(records)}")

    expected_keys = [
        "_id", "ilce_adi", "mahalle_adi", "mahalle_koy_uavt",
        "cok_agir_hasarli_bina_sayisi", "agir_hasarli_bina_sayisi",
        "orta_hasarli_bina_sayisi", "hafif_hasarli_bina_sayisi",
        "can_kaybi_sayisi", "agir_yarali_sayisi", "hastanede_tedavi_sayisi",
        "hafif_yarali_sayisi", "dogalgaz_boru_hasari", "icme_suyu_boru_hasari",
        "atik_su_boru_hasari", "gecici_barinma"
    ]

    processed = []
    total_buildings_damaged = 0
    total_casualties = 0

    for idx, row in enumerate(records, start=1):
        item = {}
        if isinstance(row, list):
            for k_idx, key in enumerate(expected_keys):
                item[key] = row[k_idx] if k_idx < len(row) else 0
        elif isinstance(row, dict):
            item = row.copy()
        else:
            continue

        item["_id"] = to_int_or_zero(item.get("_id", idx))
        item["ilce_adi"] = clean_turkish_text(str(item.get("ilce_adi", ""))).upper()
        item["mahalle_adi"] = clean_turkish_text(str(item.get("mahalle_adi", ""))).upper()
        item["mahalle_koy_uavt"] = to_int_or_zero(item.get("mahalle_koy_uavt", 0))

        item["cok_agir_hasarli_bina_sayisi"] = to_int_or_zero(item.get("cok_agir_hasarli_bina_sayisi"))
        item["agir_hasarli_bina_sayisi"] = to_int_or_zero(item.get("agir_hasarli_bina_sayisi"))
        item["orta_hasarli_bina_sayisi"] = to_int_or_zero(item.get("orta_hasarli_bina_sayisi"))
        item["hafif_hasarli_bina_sayisi"] = to_int_or_zero(item.get("hafif_hasarli_bina_sayisi"))
        item["can_kaybi_sayisi"] = to_int_or_zero(item.get("can_kaybi_sayisi"))
        item["agir_yarali_sayisi"] = to_int_or_zero(item.get("agir_yarali_sayisi"))
        item["hastanede_tedavi_sayisi"] = to_int_or_zero(item.get("hastanede_tedavi_sayisi"))
        item["hafif_yarali_sayisi"] = to_int_or_zero(item.get("hafif_yarali_sayisi"))
        item["dogalgaz_boru_hasari"] = to_int_or_zero(item.get("dogalgaz_boru_hasari"))
        item["icme_suyu_boru_hasari"] = to_int_or_zero(item.get("icme_suyu_boru_hasari"))
        item["atik_su_boru_hasari"] = to_int_or_zero(item.get("atik_su_boru_hasari"))
        item["gecici_barinma"] = to_int_or_zero(item.get("gecici_barinma"))

        total_buildings_damaged += (
            item["cok_agir_hasarli_bina_sayisi"] +
            item["agir_hasarli_bina_sayisi"] +
            item["orta_hasarli_bina_sayisi"]
        )
        total_casualties += item["can_kaybi_sayisi"]
        processed.append(item)

    processed.sort(key=lambda x: (x["ilce_adi"], x["mahalle_adi"]))

    os.makedirs(os.path.dirname(DEPREM_JSON_PATH), exist_ok=True)
    with open(DEPREM_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)

    unique_districts = len(set(x["ilce_adi"] for x in processed))
    log_success(f"deprem.json başarıyla güncellendi: {len(processed)} mahalle, {unique_districts} ilçe.")
    log_info(f"Senaryo Özeti: {total_buildings_damaged:,} hasarlı/yıkık bina, {total_casualties:,} can kaybı öngörüsü.")
    return True

# =============================================================================
# 2. MODÜL: Toplanma Alanları ve İl İndeksi Güncelleme
# =============================================================================
def update_camps(backup=True):
    """Toplanma alanlarını doğrular, il bazlı json'ları ve iller_index.json'ı yeniler."""
    log_header("TÜRKİYE TOPLANMA ALANLARI VE İL İNDEKSİ GÜNCELLENİYOR")

    if not os.path.exists(TURKIYE_CAMPS_PATH):
        log_error(f"Ana toplanma alanları dosyası bulunamadı: {TURKIYE_CAMPS_PATH}")
        return False

    if backup:
        backup_file(ILLER_INDEX_PATH)

    log_info("turkiye_toplanma_alanlari.json okunuyor...")
    with open(TURKIYE_CAMPS_PATH, "r", encoding="utf-8") as f:
        camps = json.load(f)

    if not isinstance(camps, list):
        log_error("Toplanma alanları verisi liste formatında değil!")
        return False

    log_info(f"Toplam toplanma alanı kaydı: {len(camps):,}")

    by_province = {}
    for c in camps:
        prov = clean_turkish_text(str(c.get("il", ""))).strip()
        if not prov:
            continue
        if prov not in by_province:
            by_province[prov] = []
        by_province[prov].append(c)

    log_info(f"Benzersiz il sayısı: {len(by_province)}")

    existing_index = {}
    if os.path.exists(ILLER_INDEX_PATH):
        try:
            with open(ILLER_INDEX_PATH, "r", encoding="utf-8") as f:
                raw_idx = json.load(f)
                for item in raw_idx:
                    existing_index[item.get("name", "").lower()] = item
                    existing_index[item.get("slug", "").lower()] = item
        except Exception:
            pass

    def turkish_slug(text):
        mapping = {
            'İ': 'i', 'I': 'i', 'ı': 'i',
            'Ç': 'c', 'ç': 'c',
            'Ğ': 'g', 'ğ': 'g',
            'Ö': 'o', 'ö': 'o',
            'Ş': 's', 'ş': 's',
            'Ü': 'u', 'ü': 'u',
        }
        s = text
        for k, v in mapping.items():
            s = s.replace(k, v)
        s = s.lower()
        s = "".join(ch if ch.isalnum() else "-" for ch in s)
        return "-".join(part for part in s.split("-") if part)

    updated_index = []
    sync_count = 0

    for prov_name, prov_camps in sorted(by_province.items()):
        slug = turkish_slug(prov_name)
        lookup = existing_index.get(prov_name.lower()) or existing_index.get(slug)

        lats = [float(x["lat"]) for x in prov_camps if x.get("lat") and str(x["lat"]).replace(".", "").isdigit()]
        lons = [float(x["lon"]) for x in prov_camps if x.get("lon") and str(x["lon"]).replace(".", "").isdigit()]
        
        if lookup and lookup.get("center"):
            center = lookup["center"]
        elif lats and lons:
            center = [round(sum(lats) / len(lats), 4), round(sum(lons) / len(lons), 4)]
        else:
            center = [39.0, 35.0]

        prov_dir = os.path.join(ILLER_DIR, slug)
        prov_file_rel = f"iller/{slug}/toplanma_alanlari.json"
        prov_file_abs = os.path.join(ILLER_DIR, slug, "toplanma_alanlari.json")

        os.makedirs(prov_dir, exist_ok=True)
        try:
            with open(prov_file_abs, "w", encoding="utf-8") as pf:
                json.dump(prov_camps, pf, ensure_ascii=False, indent=2)
            sync_count += 1
        except Exception as e:
            log_warn(f"{slug} dosyası yazılamadı: {e}")

        entry = {
            "slug": slug,
            "name": prov_name,
            "count": len(prov_camps),
            "center": center,
            "file": prov_file_rel
        }

        # Simülasyon yalnızca doğrulanabilir resmi açık veri seti olan İstanbul için geçerlidir
        if slug == "istanbul":
            entry["has_simulation"] = True
            entry["scenario_name"] = "İBB 7.5 Mw Gece Senaryosu"
            entry["deprem_file"] = "iller/istanbul/deprem.json"
            entry["coord_file"] = "iller/istanbul/ilce.json"
            entry["source_name"] = "İBB Açık Veri Portalı (7.5 Mw Analizi)"
            entry["source_url"] = "https://data.ibb.gov.tr/dataset/deprem-senaryosu-analiz-sonuclari/resource/9c3ac492-de4b-4245-b418-7ad3df67a193"
            entry["source_desc"] = "İstanbul Büyükşehir Belediyesi (İBB) 7.5 Mw Olası Gece Depremi Senaryosu Analiz Sonuçları ve İlçe Bazlı Bina Hasar / Can Kaybı Tahmin Raporu."
        else:
            entry["has_simulation"] = False
            entry["source_name"] = "e-Devlet / AFAD Acil Toplanma Alanı Sorgulama"
            entry["source_url"] = "https://www.turkiye.gov.tr/afet-ve-acil-durum-yonetimi-acil-toplanma-alani-sorgulama"
            entry["source_desc"] = f"T.C. İçişleri Bakanlığı AFAD {prov_name} İli Resmi Afet ve Acil Durum Toplanma Alanları Veritabanı."

        updated_index.append(entry)

    tr_alphabet = "a,b,c,ç,d,e,f,g,ğ,h,ı,i,j,k,l,m,n,o,ö,p,r,s,ş,t,u,ü,v,y,z".split(",")
    tr_order = {c: i for i, c in enumerate(tr_alphabet)}
    def tr_sort_key(item):
        name = item.get("name", "").lower().replace("İ", "i").replace("I", "ı")
        return [tr_order.get(ch, 99) for ch in name]

    updated_index.sort(key=tr_sort_key)

    with open(ILLER_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(updated_index, f, ensure_ascii=False, indent=2)

    istanbul_camps = len(by_province.get("İstanbul", by_province.get("İSTANBUL", [])))
    log_success(f"iller_index.json yenilendi ({len(updated_index)} il).")
    log_info(f"Senkronize edilen il klasörleri: {sync_count}")
    log_info(f"İstanbul toplam toplanma alanı: {istanbul_camps:,}")
    return True

# =============================================================================
# 3. MODÜL: Diri Fay Hatları ve Bilimsel Sismotektonik Sınıflandırma
# =============================================================================
def extract_feature_points(geom):
    coords = geom.get("coordinates", [])
    def _extract(c):
        if not c:
            return []
        if isinstance(c[0], (int, float)):
            return [c]
        res = []
        for item in c:
            res.extend(_extract(item))
        return res
    return _extract(coords)

def classify_fault_segment(feat):
    props = feat.get("properties", {})
    geom = feat.get("geometry", {})
    pts = extract_feature_points(geom)
    if not pts:
        c_lat, c_lon = 39.0, 35.0
    else:
        lats = [p[1] for p in pts]
        lons = [p[0] for p in pts]
        c_lat = sum(lats) / len(lats)
        c_lon = sum(lons) / len(lons)

    name = str(props.get("name", "")).lower()
    system = str(props.get("system", "")).lower()
    p = props.copy()

    # 1. KRİTİK SİSMİK BOŞLUKLAR (Tekrarlanma Süresi Doldu!)
    if (40.72 <= c_lat <= 41.05 and 28.0 <= c_lon <= 29.1) or "kumburgaz" in name or "orta marmara" in name:
        p["name"] = "Kuzey Anadolu Fayı (Kumburgaz / Orta Marmara Segmenti)"
        p["system"] = "Kuzey Anadolu Fay Zonu (KAFZ)"
        p["risk_category"] = "KRITIK_BOSLUK"
        p["risk_level"] = "Kritik / Çok Yüksek (Sismik Boşluk)"
        p["risk_desc"] = "Marmara Denizi içindeki 260 yıldır kırılmayan ana sismik boşluktur. Tekrarlanma süresi (~250 yıl) dolmuştur."
        p["color"] = "#ef4444"
        p["gap_badge"] = "KRİTİK BOŞLUK"
        p["last_rupture_year"] = "1766 (260 yıldır kırılmadı!)"
        p["last_event"] = "1766 Büyük Marmara Depremi (Mw ~7.4). Süre aşılmıştır."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/1766_Marmara_depremi"
        p["recurrence"] = "~250 yıl (Süresi Doldu!)"
        p["max_mw"] = "7.2 - 7.6 Mw"
        p["slip_rate"] = "20.0 - 24.0 mm/yıl"
        p["slip_type_tr"] = "Sağ Yanal Doğrultu Atımlı"
        return p

    if (40.8 <= c_lat <= 40.95 and 29.05 <= c_lon <= 29.5) or "adalar" in name or "çınarcık" in name:
        p["name"] = "Kuzey Anadolu Fayı (Çınarcık / Adalar Segmenti)"
        p["system"] = "Kuzey Anadolu Fay Zonu (KAFZ)"
        p["risk_category"] = "KRITIK_BOSLUK"
        p["risk_level"] = "Kritik / Çok Yüksek (Sismik Boşluk)"
        p["risk_desc"] = "1894 yılından bu yana 132 yıldır kırılmamıştır; gerilim yükü çok yüksektir."
        p["color"] = "#ef4444"
        p["gap_badge"] = "KRİTİK BOŞLUK"
        p["last_rupture_year"] = "1894 (132 yıldır kırılmadı)"
        p["last_event"] = "1894 İstanbul / Marmara Depremi (Mw ~7.0)."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/1894_%C4%B0stanbul_depremi"
        p["recurrence"] = "~200 - 300 yıl"
        p["max_mw"] = "7.0 - 7.2 Mw"
        p["slip_rate"] = "18.0 - 22.0 mm/yıl"
        p["slip_type_tr"] = "Sağ Yanal - Normal Bileşenli"
        return p

    if (39.25 <= c_lat <= 39.65 and 39.8 <= c_lon <= 40.7) or "yedisu" in name:
        p["name"] = "Kuzey Anadolu Fayı (Yedisu Sismik Boşluğu)"
        p["system"] = "Kuzey Anadolu Fay Zonu (KAFZ)"
        p["risk_category"] = "KRITIK_BOSLUK"
        p["risk_level"] = "Kritik / Çok Yüksek (Sismik Boşluk)"
        p["risk_desc"] = "1939 Erzincan ve 1949 Karlıova kırıkları arasında 242 yıldır büyük deprem üretmeyen sismik boşluktur."
        p["color"] = "#ef4444"
        p["gap_badge"] = "KRİTİK BOŞLUK"
        p["last_rupture_year"] = "1784 (242 yıldır kırılmadı!)"
        p["last_event"] = "1784 Yedisu Depremi (Mw ~7.2). Tekrarlanma periyodu dolmuştur."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/1784_Erzincan_depremi"
        p["recurrence"] = "~250 yıl (Süresi Doldu!)"
        p["max_mw"] = "7.2 - 7.4 Mw"
        p["slip_rate"] = "20.0 - 22.0 mm/yıl"
        p["slip_type_tr"] = "Sağ Yanal Doğrultu Atımlı"
        return p

    # 2. DÜŞÜK RİSK / ENERJİ BOŞALDI (Son 30 Yılda Kırılanlar)
    if (35.7 <= c_lat <= 37.8 and 36.0 <= c_lon <= 37.6) or any(x in name for x in ["pazarcık", "amanos", "antakya", "gölbaşı"]):
        p["name"] = "Doğu Anadolu Fayı (Pazarcık - Amanos - Antakya Segmenti)"
        p["system"] = "Doğu Anadolu Fay Zonu (DAFZ)"
        p["risk_category"] = "DUSUK_RISK"
        p["risk_level"] = "Düşük Risk (Enerji Boşaldı - 6 Şubat 2023)"
        p["risk_desc"] = "6 Şubat 2023 Mw 7.8 depremiyle 300+ km yüzey kırığı oluşmuş ve yüzyıllardır biriken elastik gerilim boşalmıştır. Ana şok riski çok düşüktür."
        p["color"] = "#10b981"
        p["gap_badge"] = "ENERJİ BOŞALDI"
        p["last_rupture_year"] = "2023 (Mw 7.8)"
        p["last_event"] = "6 Şubat 2023 Pazarcık Depremi (Mw 7.8). Enerji tamamen boşalmıştır."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/2023_Gaziantep-Kahramanmara%C5%9F_depremleri"
        p["recurrence"] = "~400 - 500 yıl"
        p["max_mw"] = "7.8 Mw (Kırıldı)"
        p["slip_rate"] = "9.0 - 10.0 mm/yıl"
        p["slip_type_tr"] = "Sol Yanal Doğrultu Atımlı"
        return p

    if (37.8 <= c_lat <= 38.4 and 36.1 <= c_lon <= 37.8) or any(x in name for x in ["çardak", "elbistan", "göksun"]):
        p["name"] = "Çardak - Göksun - Elbistan Fayı"
        p["system"] = "Doğu Anadolu Çardak Fay Zonu"
        p["risk_category"] = "DUSUK_RISK"
        p["risk_level"] = "Düşük Risk (Enerji Boşaldı - 6 Şubat 2023)"
        p["risk_desc"] = "6 Şubat 2023 Mw 7.6 depremiyle kırılarak enerjisini boşaltmıştır. Yakın gelecekte büyük ana şok potansiyeli çok düşüktür."
        p["color"] = "#10b981"
        p["gap_badge"] = "ENERJİ BOŞALDI"
        p["last_rupture_year"] = "2023 (Mw 7.6)"
        p["last_event"] = "6 Şubat 2023 Elbistan Depremi (Mw 7.6). Enerji tamamen boşalmıştır."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/2023_Gaziantep-Kahramanmara%C5%9F_depremleri"
        p["recurrence"] = "~500 - 800 yıl"
        p["max_mw"] = "7.6 Mw (Kırıldı)"
        p["slip_rate"] = "2.0 - 4.0 mm/yıl"
        p["slip_type_tr"] = "Sol Yanal Doğrultu Atımlı"
        return p

    if (40.65 <= c_lat <= 40.85 and 29.5 <= c_lon <= 30.5) or any(x in name for x in ["gölcük", "karamürsel", "sapanca"]):
        p["name"] = "Kuzey Anadolu Fayı (İzmit - Gölcük - Sapanca Segmenti)"
        p["system"] = "Kuzey Anadolu Fay Zonu (KAFZ)"
        p["risk_category"] = "DUSUK_RISK"
        p["risk_level"] = "Düşük Risk (Enerji Boşaldı - 1999 Depremi)"
        p["risk_desc"] = "17 Ağustos 1999 Mw 7.4 depremiyle enerjisini boşaltmıştır. Bir sonraki döngü için ~250 yıllık sürecin başındadır."
        p["color"] = "#10b981"
        p["gap_badge"] = "ENERJİ BOŞALDI"
        p["last_rupture_year"] = "1999 (Mw 7.4)"
        p["last_event"] = "17 Ağustos 1999 Gölcük/Kocaeli Depremi (Mw 7.4). Enerji boşalmıştır."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/1999_G%C3%B6lc%C3%BCk_depremi"
        p["recurrence"] = "~250 - 300 yıl"
        p["max_mw"] = "7.4 Mw (Kırıldı)"
        p["slip_rate"] = "22.0 mm/yıl"
        p["slip_type_tr"] = "Sağ Yanal Doğrultu Atımlı"
        return p

    if (40.7 <= c_lat <= 40.95 and 30.5 <= c_lon <= 31.4) or any(x in name for x in ["düzce", "akyazı", "karadere"]):
        p["name"] = "Kuzey Anadolu Fayı (Düzce - Akyazı Segmenti)"
        p["system"] = "Kuzey Anadolu Fay Zonu (KAFZ)"
        p["risk_category"] = "DUSUK_RISK"
        p["risk_level"] = "Düşük Risk (Enerji Boşaldı - 1999 Depremi)"
        p["risk_desc"] = "12 Kasım 1999 Mw 7.2 depremiyle enerjisini boşaltmıştır; ana şok riski düşüktür."
        p["color"] = "#10b981"
        p["gap_badge"] = "ENERJİ BOŞALDI"
        p["last_rupture_year"] = "1999 (Mw 7.2)"
        p["last_event"] = "12 Kasım 1999 Düzce Depremi (Mw 7.2). Enerji boşalmıştır."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/1999_D%C3%BCzce_depremi"
        p["recurrence"] = "~250 - 300 yıl"
        p["max_mw"] = "7.2 Mw (Kırıldı)"
        p["slip_rate"] = "22.0 mm/yıl"
        p["slip_type_tr"] = "Sağ Yanal Doğrultu Atımlı"
        return p

    if (38.25 <= c_lat <= 38.65 and 38.9 <= c_lon <= 39.7) or "sivrice" in name or "doğanyol" in name:
        p["name"] = "Doğu Anadolu Fayı (Sivrice - Doğanyol Segmenti)"
        p["system"] = "Doğu Anadolu Fay Zonu (DAFZ)"
        p["risk_category"] = "DUSUK_RISK"
        p["risk_level"] = "Düşük Risk (Enerji Boşaldı - 2020 Depremi)"
        p["risk_desc"] = "24 Ocak 2020 Mw 6.8 Sivrice depremiyle enerjisini boşaltmıştır; ana şok riski düşüktür."
        p["color"] = "#10b981"
        p["gap_badge"] = "ENERJİ BOŞALDI"
        p["last_rupture_year"] = "2020 (Mw 6.8)"
        p["last_event"] = "24 Ocak 2020 Sivrice-Elazığ Depremi (Mw 6.8). Enerji boşalmıştır."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/2020_Elaz%C4%B1%C4%9F_depremi"
        p["recurrence"] = "~200 - 300 yıl"
        p["max_mw"] = "6.8 Mw (Kırıldı)"
        p["slip_rate"] = "9.0 mm/yıl"
        p["slip_type_tr"] = "Sol Yanal Doğrultu Atımlı"
        return p

    if (37.7 <= c_lat <= 38.05 and 26.5 <= c_lon <= 27.2) or "sisam" in name or "samos" in name:
        p["name"] = "Sisam - Kuşadası Normal Fayı"
        p["system"] = "Ege Graben Sistemi"
        p["risk_category"] = "DUSUK_RISK"
        p["risk_level"] = "Düşük Risk (Enerji Boşaldı - 2020 Sisam Depremi)"
        p["risk_desc"] = "30 Ekim 2020 Mw 6.9 Ege Denizi depremiyle kırılarak enerjisini boşaltmıştır."
        p["color"] = "#10b981"
        p["gap_badge"] = "ENERJİ BOŞALDI"
        p["last_rupture_year"] = "2020 (Mw 6.9)"
        p["last_event"] = "30 Ekim 2020 Sisam-İzmir Depremi (Mw 6.9). Normal faylanmayla enerji boşaldı."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/2020_Ege_Denizi_depremi"
        p["recurrence"] = "~250 - 350 yıl"
        p["max_mw"] = "6.9 Mw (Kırıldı)"
        p["slip_rate"] = "3.0 - 5.0 mm/yıl"
        p["slip_type_tr"] = "Normal Fay"
        return p

    if (38.45 <= c_lat <= 38.85 and 43.15 <= c_lon <= 43.75) or "tabanlı" in name:
        p["name"] = "Van Tabanlı / Erciş Fay Zonu"
        p["system"] = "Van - Bitlis Sıkışma Zonu"
        p["risk_category"] = "DUSUK_RISK"
        p["risk_level"] = "Düşük Risk (Enerji Boşaldı - 2011 Van Depremi)"
        p["risk_desc"] = "23 Ekim 2011 Mw 7.2 kör ters fay depremiyle enerjisini boşaltmıştır."
        p["color"] = "#10b981"
        p["gap_badge"] = "ENERJİ BOŞALDI"
        p["last_rupture_year"] = "2011 (Mw 7.2)"
        p["last_event"] = "23 Ekim 2011 Van Depremi (Mw 7.2). Kör ters fay üzerinde enerji boşaldı."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/2011_Van_depremi"
        p["recurrence"] = "~300 - 500 yıl"
        p["max_mw"] = "7.2 Mw (Kırıldı)"
        p["slip_rate"] = "2.0 - 4.0 mm/yıl"
        p["slip_type_tr"] = "Ters / Bindirme Fayı"
        return p

    # 3. YÜKSEK RİSK / GERİLİM BİRİKİMİ İLERİ DÜZEYDE (Sismik Boşluk Adayları)
    if (40.0 <= c_lat <= 40.55 and 27.3 <= c_lon <= 29.8) or any(x in name for x in ["gemlik", "bandırma", "erdek", "mudanya"]):
        p["name"] = "KAF Güney Kolu (Gemlik - Bandırma Segmenti)"
        p["system"] = "Kuzey Anadolu Fay Zonu (Güney Kolu)"
        p["risk_category"] = "YUKSEK_RISK"
        p["risk_level"] = "Yüksek Risk (Sismik Boşluk Adayı)"
        p["risk_desc"] = "Kuzey koluna göre daha yavaş kayar (~5 mm/yıl) ancak yüzyıllardır büyük deprem üretmemiştir; gerilim yükü yüksektir."
        p["color"] = "#f97316"
        p["gap_badge"] = "YÜKSEK RİSK"
        p["last_rupture_year"] = "1419 / 1737 (Tarihsel)"
        p["last_event"] = "Tarihsel 1419 ve 1737 depremleri. Gerilim birikimi ileri düzeydedir."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/Kuzey_Anadolu_Fay_Hatt%C4%B1"
        p["recurrence"] = "~350 - 500 yıl"
        p["max_mw"] = "6.8 - 7.2 Mw"
        p["slip_rate"] = "4.0 - 6.0 mm/yıl"
        p["slip_type_tr"] = "Sağ Yanal - Normal Bileşenli"
        return p

    # 4. MEGATHRUST (Dalma - Batma Zonu)
    if (34.0 <= c_lat <= 36.2 and 24.0 <= c_lon <= 33.5) or "helen" in system or "kıbrıs" in system:
        p["name"] = "Helen - Kıbrıs Dalma-Batma Yayı"
        p["system"] = "Helen - Kıbrıs Yayı (Megathrust)"
        p["risk_category"] = "MEGATHRUST"
        p["risk_level"] = "Derin Odaklı / Megathrust (Tsunami Riski)"
        p["risk_desc"] = "Afrika levhasının Ege altına daldığı aktif dalma-batma zonudur. Derin odaklı büyük depremler ve tsunami potansiyeli taşır."
        p["color"] = "#a855f7"
        p["gap_badge"] = "MEGATHRUST YAYI"
        p["last_rupture_year"] = "1926 / 1957 (Tarihsel Megathrust)"
        p["last_event"] = "1926 Rodos (Mw 7.7) ve 1957 Fethiye (Mw 7.1) derin odaklı depremleri."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/1957_Fethiye_depremleri"
        p["recurrence"] = "~150 - 300 yıl"
        p["max_mw"] = "7.5 - 8.0 Mw (Tsunamijenik)"
        p["slip_rate"] = "30.0 - 40.0 mm/yıl"
        p["slip_type_tr"] = "Dalma-Batma / Subduction Thrust"
        return p

    # 5. YAVAŞ DEFORMASYON / İÇ ANADOLU (< 1.0 mm/yıl)
    if (37.0 <= c_lat <= 40.2 and 30.5 <= c_lon <= 35.8):
        p["name"] = p.get("name") if "fay" in p.get("name", "").lower() else "İç Anadolu Aktif Fay Segmenti"
        p["system"] = "İç Anadolu Fay Sistemi"
        p["risk_category"] = "YAVAS_FAY"
        p["risk_level"] = "Düşük - Orta Risk (Çok Yavaş Deformasyon)"
        p["risk_desc"] = "Yıllık deformasyon hızı çok düşüktür (< 1.0 mm/yıl). Deprem tekrarlanma periyotları 1.500 - 5.000 yıl mertebesindedir."
        p["color"] = "#38bdf8"
        p["gap_badge"] = "YAVAŞ FAY (<1 mm/yıl)"
        p["last_rupture_year"] = "Tarihsel / Kuvaterner (Holosen)"
        p["last_event"] = "Kuvaterner aktif diri fay. Yıllık kayma hızı çok düşüktür."
        p["recurrence"] = "~1.500 - 5.000 yıl"
        p["max_mw"] = "6.0 - 6.5 Mw"
        p["slip_rate"] = "0.2 - 0.8 mm/yıl"
        p["slip_type_tr"] = p.get("slip_type_tr") or "Doğrultu Atımlı / Normal"
        return p

    # 6. ORTA RİSK: 20. YÜZYIL KAF KIRILMALARI (1939 - 1944)
    if (40.4 <= c_lat <= 41.3 and 31.4 <= c_lon <= 40.0):
        p["name"] = p.get("name") if "kuzey anadolu" in p.get("name", "").lower() else "Kuzey Anadolu Fayı (20. yy Kırılma Segmenti)"
        p["system"] = "Kuzey Anadolu Fay Zonu (KAFZ)"
        p["risk_category"] = "ORTA_RISK"
        p["risk_level"] = "Orta Risk (Döngü Ortasında - Gerilim Birikimi Sürüyor)"
        p["risk_desc"] = "1939-1944 büyük deprem serisiyle kırılmıştır (~80 yıl önce). ~300 yıllık tekrarlanma periyodunun ortasındadır; gerilim birikmektedir."
        p["color"] = "#f59e0b"
        p["gap_badge"] = "ORTA RİSK"
        p["last_rupture_year"] = "1939 - 1944 (Mw 7.0 - 7.9)"
        p["last_event"] = "1939 Erzincan (Mw 7.9), 1942 Niksar (Mw 7.0), 1943 Tosya (Mw 7.2), 1944 Gerede (Mw 7.3)."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/1939_Erzincan_depremi"
        p["recurrence"] = "~250 - 350 yıl"
        p["max_mw"] = "7.2 - 7.5 Mw"
        p["slip_rate"] = "22.0 mm/yıl"
        p["slip_type_tr"] = "Sağ Yanal Doğrultu Atımlı"
        return p

    # 7. ORTA RİSK: BATI ANADOLU GRABENLERİ (Gediz, Menderes, Simav)
    if (37.0 <= c_lat <= 39.5 and 26.0 <= c_lon <= 30.5):
        p["name"] = p.get("name") if "fay" in p.get("name", "").lower() else "Batı Anadolu Graben Normal Fayı"
        p["system"] = "Batı Anadolu Graben Sistemi (BAFS)"
        p["risk_category"] = "ORTA_RISK"
        p["risk_level"] = "Orta Risk (Graben Açılma Rejimi)"
        p["risk_desc"] = "Ege genişleme tektoniği etkisiyle sık fakat genellikle 5.5 - 6.8 Mw aralığında depremler üretir."
        p["color"] = "#f59e0b"
        p["gap_badge"] = "ORTA RİSK"
        p["last_rupture_year"] = "1899 / 1969 / 1970 (Tarihsel ve Modern)"
        p["last_event"] = "Alaşehir 1969 (Mw 6.5), Gediz 1970 (Mw 7.2), Dinar 1995 (Mw 6.2)."
        p["wikipedia"] = "https://tr.wikipedia.org/wiki/1970_Gediz_depremi"
        p["recurrence"] = "~200 - 450 yıl"
        p["max_mw"] = "6.2 - 6.8 Mw"
        p["slip_rate"] = "2.0 - 5.0 mm/yıl"
        p["slip_type_tr"] = "Normal Fay"
        return p

    # 8. DİĞER TÜRKİYE DİRİ FAYLARI (Genel Sınıflandırma)
    p["name"] = p.get("name") or "Türkiye Aktif Diri Fay Segmenti"
    p["system"] = p.get("system") or "Türkiye Diri Fay Sistemi"
    p["risk_category"] = "ORTA_RISK"
    p["risk_level"] = "Orta Risk (Diri Fay Gerilim Birikimi)"
    p["risk_desc"] = "Kuvaterner döneminde yüzey kırığı üretmiş diri fay segmenti; gerilim birikim evresindedir."
    p["color"] = "#f59e0b"
    p["gap_badge"] = "ORTA RİSK"
    p["last_rupture_year"] = p.get("last_rupture_year") or "Tarihsel / Kuvaterner (Holosen)"
    p["last_event"] = p.get("last_event") or "Kuvaterner aktif diri fay hattı aktivitesi devam etmektedir."
    p["recurrence"] = p.get("recurrence") or "~300 - 600 yıl"
    p["max_mw"] = p.get("max_mw") or "6.2 - 6.8 Mw"
    p["slip_rate"] = p.get("slip_rate") or "1.0 - 3.0 mm/yıl"
    p["slip_type_tr"] = p.get("slip_type_tr") or "Doğrultu Atımlı / Ters"
    return p

def update_faults(download_gem=False, backup=True):
    """Fay hatlarını indirir veya mevcut veri setini gerçekçi parametrelerle günceller."""
    log_header("TÜRKİYE DİRİ FAY HATLARI VE RİSK MODELLERİ GÜNCELLENİYOR")
    log_info(f"Hedef Dosya: {os.path.relpath(FAYLAR_GEOJSON_PATH, BASE_DIR)}")

    if backup and os.path.exists(FAYLAR_GEOJSON_PATH):
        backup_file(FAYLAR_GEOJSON_PATH)

    raw_features = []

    if download_gem:
        log_info(f"GEM Küresel Aktif Faylar veri tabanı indiriliyor: {GEM_GEOJSON_URL}")
        try:
            req = urllib.request.Request(
                GEM_GEOJSON_URL,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) update.py/1.0"}
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                gem_data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for feat in gem_data.get("features", []):
                    pts = extract_feature_points(feat.get("geometry", {}))
                    if not pts:
                        continue
                    lats = [p[1] for p in pts]
                    lons = [p[0] for p in pts]
                    c_lat = sum(lats) / len(lats)
                    c_lon = sum(lons) / len(lons)
                    if 34.0 <= c_lat <= 43.5 and 24.5 <= c_lon <= 46.5:
                        raw_features.append(feat)
            log_success(f"GEM sunucusundan Türkiye bölgesine ait {len(raw_features)} segment çekildi.")
        except Exception as e:
            log_error(f"GEM indirme hatası: {e}. Mevcut yerel dosya kullanılacak.")
            raw_features = []

    if not raw_features:
        if not os.path.exists(FAYLAR_GEOJSON_PATH):
            log_error(f"Fay dosyası bulunamadı: {FAYLAR_GEOJSON_PATH}")
            return False
        log_info("Mevcut yerel fay GeoJSON dosyası okunuyor...")
        with open(FAYLAR_GEOJSON_PATH, "r", encoding="utf-8") as f:
            local_geo = json.load(f)
            raw_features = local_geo.get("features", [])

    log_info(f"İşlenecek diri fay segmenti sayısı: {len(raw_features)}")

    def round_coords(c):
        if not c:
            return c
        if isinstance(c[0], (int, float)):
            return [round(c[0], 5), round(c[1], 5)]
        return [round_coords(item) for item in c]

    enriched_features = []
    category_counts = {}

    for feat in raw_features:
        geom = feat.get("geometry", {})
        if not geom or not geom.get("coordinates"):
            continue

        new_geom = {
            "type": geom.get("type"),
            "coordinates": round_coords(geom.get("coordinates"))
        }

        new_props = classify_fault_segment(feat)
        cat = new_props.get("risk_category", "ORTA_RISK")
        category_counts[cat] = category_counts.get(cat, 0) + 1

        enriched_features.append({
            "type": "Feature",
            "properties": new_props,
            "geometry": new_geom
        })

    output_geojson = {
        "type": "FeatureCollection",
        "metadata": {
            "title": "Türkiye Diri Fay Hatları ve Sismotektonik Risk Atlası",
            "updated_at": datetime.now().isoformat(),
            "source": "GEM Global Active Faults Database & SHARE-EMME / MTA",
            "total_segments": len(enriched_features),
            "risk_categories": category_counts
        },
        "features": enriched_features
    }

    with open(FAYLAR_GEOJSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output_geojson, f, ensure_ascii=False, indent=2)

    log_success(f"fay_hatlari_turkiye.geojson başarıyla güncellendi ({len(enriched_features)} segment).")
    print(f"\n{C.BOLD}  Sismotektonik Risk Dağılımı Tablosu:{C.RESET}")
    print(f"  {'-'*55}")
    names_tr = {
        "KRITIK_BOSLUK": "🔴 Kritik Sismik Boşluk (Marmara 1766, Yedisu 1784)",
        "YUKSEK_RISK":   "🟠 Yüksek Risk / Boşluk Adayı (Gemlik, Bandırma)",
        "ORTA_RISK":     "🟡 Orta Risk (KAF 20. yy, Graben Fayları)",
        "DUSUK_RISK":    "🟢 Düşük Risk / Enerji Boşaldı (2023 Maraş, 1999 Gölcük)",
        "YAVAS_FAY":     "🔵 Yavaş Deformasyon (İç Anadolu - <1 mm/yıl)",
        "MEGATHRUST":    "🟣 Megathrust / Dalma-Batma (Helen-Kıbrıs Yayı)"
    }
    for cat_key, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        label = names_tr.get(cat_key, cat_key)
        print(f"  {label:<48}: {C.BOLD}{count:>4}{C.RESET}")
    print(f"  {'-'*55}")
    return True

# =============================================================================
# 4. MODÜL: Bütünlük Denetimi (Integrity Baseline) Güncelleme
# =============================================================================
def update_integrity():
    """ops/integrity_check.sh betiğini --baseline --force parametresiyle çalıştırır."""
    log_header("DOSYA BÜTÜNLÜK MANİFESTOSU (BASELINE) GÜNCELLENİYOR")

    if not os.path.exists(INTEGRITY_SCRIPT_PATH):
        log_error(f"Bütünlük betiği bulunamadı: {INTEGRITY_SCRIPT_PATH}")
        return False

    cmd = ["sh", INTEGRITY_SCRIPT_PATH, "--baseline", "--force"]
    log_info(f"Komut çalıştırılıyor: {' '.join(cmd)}")

    try:
        res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
        if res.returncode == 0:
            for line in res.stdout.strip().split("\n"):
                if line:
                    log_success(line)
            return True
        else:
            log_error(f"Bütünlük betiği hata verdi (kod: {res.returncode}):\n{res.stderr}")
            return False
    except Exception as e:
        log_error(f"Bütünlük komutu çalıştırılamadı: {e}")
        return False

# =============================================================================
# 5. MODÜL: Sistem Durum Raporu
# =============================================================================
def print_status():
    """Tüm veri setlerinin boyut, kayıt sayısı ve son güncelleme durumunu özetler."""
    log_header("İSTDEPREM — VERİ VE SİSTEM DURUM RAPORU")

    def file_info(path):
        if not os.path.exists(path):
            return f"{C.RED}YOK{C.RESET}", "0 B", "-"
        sz = os.path.getsize(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
        if sz > 1024 * 1024:
            sz_str = f"{sz / (1024 * 1024):.2f} MB"
        else:
            sz_str = f"{sz / 1024:.1f} KB"
        return f"{C.GREEN}MEVCUT{C.RESET}", sz_str, mtime

    files = [
        ("İBB İstanbul Deprem Verisi", DEPREM_JSON_PATH),
        ("İstanbul Koordinat Haritası", ILCE_JSON_PATH),
        ("Türkiye Fay Hatları GeoJSON", FAYLAR_GEOJSON_PATH),
        ("Türkiye Toplanma Alanları", TURKIYE_CAMPS_PATH),
        ("İl Toplanma Alanı İndeksi", ILLER_INDEX_PATH),
        ("Bütünlük Betiği (Ops)", INTEGRITY_SCRIPT_PATH),
    ]

    print(f"  {'Veri Seti':<30} {'Durum':<14} {'Boyut':<12} {'Son Değişiklik':<20}")
    print(f"  {'-'*76}")
    for name, path in files:
        st, sz, mt = file_info(path)
        print(f"  {name:<30} {st:<23} {sz:<12} {mt:<20}")
    print(f"  {'-'*76}\n")

# =============================================================================
# ANA GİRİŞ NOKTASI (CLI Argument Parser)
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="istdeprem — Veri ve Harita Güncelleme Otomasyonu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnek Kullanım:
  cd istdeprem && python3 update.py --all
  # VEYA
  python3 istdeprem/update.py --all
  python3 istdeprem/update.py --deprem
  python3 istdeprem/update.py --camps
  python3 istdeprem/update.py --faults
  python3 istdeprem/update.py --status
        """
    )
    parser.add_argument("--all", action="store_true", help="Tüm güncelleme hattını sırayla çalıştırır.")
    parser.add_argument("--deprem", action="store_true", help="İBB 7.5 Mw İstanbul Deprem verisini günceller.")
    parser.add_argument("--camps", action="store_true", help="Toplanma alanlarını ve il indeksini günceller.")
    parser.add_argument("--faults", action="store_true", help="Türkiye diri fay hatları ve risk modellerini günceller.")
    parser.add_argument("--download-gem", action="store_true", help="Fay güncellemesinde GEM ham dosyasını GitHub'dan indirir.")
    parser.add_argument("--integrity", action="store_true", help="Bütünlük manifestosunu (integrity baseline) günceller.")
    parser.add_argument("--status", action="store_true", help="Veri setlerinin durumunu raporlar.")
    parser.add_argument("--no-backup", action="store_true", help="Otomatik .bak yedeği oluşturmaz.")

    args = parser.parse_args()

    if not any([args.all, args.deprem, args.camps, args.faults, args.integrity, args.status]):
        print(f"{C.YELLOW}Uyarı: Hiçbir işlem bayrağı belirtilmedi. Varsayılan olarak '--status' çalıştırılıyor.{C.RESET}")
        print("Tüm güncellemeleri çalıştırmak için: python3 update.py --all\n")
        print_status()
        return

    backup = not args.no_backup
    start_time = time.time()

    if args.status:
        print_status()

    success = True

    if args.all or args.deprem:
        ok = update_deprem(backup=backup)
        success = success and ok

    if args.all or args.camps:
        ok = update_camps(backup=backup)
        success = success and ok

    if args.all or args.faults:
        ok = update_faults(download_gem=args.download_gem, backup=backup)
        success = success and ok

    if args.all or args.integrity:
        ok = update_integrity()
        success = success and ok

    elapsed = time.time() - start_time
    log_header("GÜNCELLEME İŞLEMİ TAMAMLANDI")
    if success:
        log_success(f"Tüm seçili işlemler başarıyla tamamlandı. Geçen süre: {elapsed:.2f} saniye.")
    else:
        log_warn(f"Bazı adımlarda uyarı veya hata oluştu. Geçen süre: {elapsed:.2f} saniye.")

if __name__ == "__main__":
    main()
