# 🌐 Canlı Çeviri Botu (Live Translation Bot)

Bu proje, **Pipecat** altyapısını kullanarak gerçek zamanlı, düşük gecikmeli ve yüksek kaliteli sesli çeviri hizmeti sunan modüler bir bottur. OpenAI (LLM), ElevenLabs/Deepgram (TTS & STT) ve Gladia gibi son teknoloji yapay zeka servislerini entegre eder.


## 🌟 Temel Özellikler

- **⚡ Gerçek Zamanlı Çeviri:** Konuşmayı anlık olarak metne döküp (STT), çevirip (LLM) ve tekrar seslendirir (TTS).
- **🎛️ Gelişmiş Admin Paneli:** Tarayıcı üzerinden (`/admin`) botun tüm ayarlarını (hız, ses, model, provider) anlık olarak değiştirebilirsiniz.
- **🔄 Hot-Swap Desteği:** Botu durdurmadan STT ve TTS sağlayıcılarını (örn: ElevenLabs -> Deepgram) değiştirebilirsiniz.
- **🔇 Akıllı Gürültü Engelleme:** **AIC Filter** (AI-Coustics) veya **RNNoise** ile arka plan gürültülerini temizler.
- **🔒 Güvenli Yönetim:** **PyJWT** tabanlı, brute-force korumalı güvenli admin girişi.
- **💬 Çoklu Provider:** 
  - **STT:** ElevenLabs, Deepgram, Gladia
  - **TTS:** ElevenLabs, Deepgram
  - **LLM:** OpenAI (GPT-4o, GPT-3.5 vb.)

---

## � Kurulum ve Başlangıç

### 1. Gereksinimler
- **Python 3.10** veya üzeri
- **FFmpeg** (Sistem yoluna eklenmiş olmalı)
- **Node.js & npm** (Daily transport kullanacaksanız, daily-client build için)
- **Git**

### 2. Projeyi İndirme ve Bağımlılıklar

Terminali açın ve aşağıdaki komutları çalıştırın:

```bash
# Bağımlılıkları yükleyin
pip install -r requirements.txt
```

### 3. Yapılandırma (.env)

Projenin çalışması için API anahtarlarına ihtiyacınız var. Örnek dosyayı kopyalayın:

```bash
cp .env.example .env
```

Ardından `.env` dosyasını bir metin editörüyle açıp gerekli alanları doldurun:

- `OPENAI_API_KEY`: Çeviri için gerekli.
- `ELEVENLABS_API_KEY`: Yüksek kaliteli seslendirme (TTS) ve STT için.
- `DEEPGRAM_API_KEY`: Alternatif hızlı STT/TTS için.
- `ADMIN_PASSWORD`: Admin paneli giriş şifreniz.
- `JWT_SECRET_KEY`: Güvenlik için rastgele, karmaşık bir metin girin.
- `DAILY_API_KEY`: Daily transport (production) için gerekli. https://pipecat.daily.co adresinden alınabilir.

---

## 🖥️ Kullanım

Botu başlatmak için ana dosya `bot_runner.py` kullanılır. İki temel mod vardır:

### A. WebRTC Modu (Canlı Yayın / Dosya)

```bash
# Bir MP3 dosyasını kaynak olarak kullanma (simülasyon)
python bot_runner.py -t webrtc --mp3-url "https://ornek.com/ses.mp3"

# Canlı yayın veya varsayılan mikrofon (argüman vermezseniz varsayılanları kullanır)
python bot_runner.py -t webrtc
```

Bot başladığında terminalde erişim linklerini göreceksiniz.

### B. Daily Modu (Production)

Daily transport, Daily.co altyapısını kullanarak güvenilir WebRTC bağlantısı sağlar. NAT traversal, yeniden bağlanma ve global altyapı dahildir.

```bash
# 1. daily-client React uygulamasını build edin (ilk seferde)
cd daily-client && npm install && npm run build && cd ..

# 2. .env dosyasında DAILY_API_KEY ayarlayın
# API key: https://pipecat.daily.co adresinden alınabilir

# 3. Botu Daily transport ile başlatın
python bot_runner.py -t daily
```

**Docker ile:**

```bash
docker compose build && docker compose up -d
```

Docker build sırasında daily-client otomatik olarak build edilir.

### C. Web Arayüzleri

Bot çalışırken tarayıcınızdan aşağıdaki adreslere gidebilirsiniz (Varsayılan port: 7860):

| Sayfa | URL | Açıklama |
|-------|-----|----------|
| **Kullanıcı Paneli** | [http://localhost:7860/client](http://localhost:7860/client) | Çeviriyi dinlemek ve izlemek için arayüz. |
| **Admin Paneli** | [http://localhost:7860/admin](http://localhost:7860/admin) | Bot ayarlarını yönetmek için kontrol merkezi. |
| **Giriş** | [http://localhost:7860/login](http://localhost:7860/login) | Admin paneline giriş sayfası. |

---

## 🎛️ Admin Paneli Kılavuzu

Admin paneline girdiğinizde sekmeler halinde ayarları göreceksiniz. Değişiklik yaptığınızda "Kaydet" butonuna basmanız yeterlidir. Çoğu ayar anlık (canlı) olarak, bazıları ise (Ses) bot yeniden başladığında uygulanır.

### 1. TTS (Metinden Sese)
- **Sağlayıcı:** ElevenLabs veya Deepgram seçebilirsiniz.
- **Ses Cinsiyeti:** "Erkek" veya "Kadın" seçtiğinizde önceden tanımlı ses ID'leri kullanılır. "Özel" seçerek kendi Voice ID'nizi girebilirsiniz.
- **Model:** Flash v2.5 (Hızlı), Turbo v2.5 vb. seçimi.
- **Hız & Stabilite:** Sesin tonunu ve hızını ayarlayın.

### 2. STT (Sesten Metne)
- **Sağlayıcı:** ElevenLabs, Deepgram veya Gladia.
- **Dil:** Kaynak sesi otomatik algılar veya sabitleyebilirsiniz.
- **VAD Ayarları:** Sessizlik algılama hassasiyetini buradan yönetin.
- **Provider Özel Ayarlar:** Smart Format (Deepgram), Code Switching (Gladia) gibi özellikleri açıp kapatabilirsiniz.

### 3. LLM (Yapay Zeka Çeviri)
- **Model:** GPT-4o, GPT-4-Turbo vb.
- **System Prompt:** Çevirmenin kişiliğini veya kurallarını (örn: "Resmi dille çevir") buradan değiştirebilirsiniz.

### 4. Audio & General
- **AIC Filtresi:** Açık/Kapalı yapabilirsiniz (Lisans anahtarı .env'de olmalı).
- **Gecikme Hedefi:** İstenen gecikme süresini (ms) ayarlayın.

---

## 🛠️ Sorun Giderme (Troubleshooting)

**S: `[Errno 10048] Address already in use` hatası alıyorum.**
C: Port 7860 dolu demektir. Başka bir bot çalışıyor olabilir. Terminali kapatıp açın veya çalışan python işlemlerini sonlandırın.

**S: Admin paneline giremiyorum, "Not authenticated" diyor.**
C: Token süresi dolmuş olabilir. Tekrar `/login` sayfasına gidip `.env` dosyasındaki şifrenizle giriş yapın.

**S: Geçiş yaparken (Hot-swap) ses kesiliyor.**
C: STT değişikliği 1-2 saniye sürebilir. Bu normaldir.

**S: Kurulumda hata alıyorum.**
C: `pip install -r requirements.txt` komutunu çalıştırdığınızdan ve internet bağlantınızın olduğundan emin olun.

---

## 📂 Proje Yapısı

- `bot_runner.py`: Ana başlangıç dosyası.
- `live_config.py`: Canlı ayar değişikliklerini yöneten modül.
- `auth.py`: Güvenlik ve JWT işlemleri.
- `providers/`: STT ve TTS servislerinin fabrika ve vekil (proxy) sınıfları.
- `daily-client/`: Daily transport için React istemci uygulaması.
- `static/`: HTML, CSS ve JS dosyaları (Admin paneli arayüzü).
- `.env`: Gizli anahtarlar ve yapılandırma.
