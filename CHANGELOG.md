## 2026-02-24 — Fast Verifier (STT Filtreleme) LLM Entegrasyonu
- **Hızlı STT Doğrulama (Fast Verifier):** Çeviri motorundan önce devreye girip STT'den gelen parçalı veya anlamsız hatalı fısıltı kelimelerini kontrol eden ek katman (Corrector LLM) eklendi.
- **`config.py` & `config_manager.py`**: `TranslationConfig` içerisine `VerifierConfig` modeli eklendi ve tüm yönetim işlemleri `config_manager._ENV_MAP` altına eklendi.
- **`processors/translator.py`**: `_run_translation` içerisine asenkron olarak "Fast Verifier" bloğu entegre edildi. Modül "DROP" dönerse pipeline kesiliyor ve token israfı önleniyor. "KEEP|" formatıyla düzeltme döndürebilir.
- **Admin Panel Desteği**: `static/admin.html` LLM paneline yeni "Fast Verifier (Hızlı Doğrulayıcı)" kartı eklendi. `static/admin.js` aracılığıyla enable/disable, provider seçimi, API Key yapılandırması arayüze taşındı. Hot-reload (canlı) güncellenebiliyor.
- **`.env.example`**: Verifier ile ilgili `VERIFIER_ENABLED`, `VERIFIER_PROVIDER` vb. tüm değişkenler eklendi.

## 2026-02-23 — .env / .env.example Düzenlemesi
- **`.env.example` ve `.env`** bölüm başlıkları ve sıra ile yeniden düzenlendi. Tüm değişkenler mantıksal gruplara ayrıldı: Admin & Auth, Genel (dil/log/gecikme), STT, TTS, LLM, Ses (AIC/audio), Buffer, Daily.co, CORS. Yinelenen ve kaldırılmış provider’a ait (Anthropic, LLM_BASE_URL) satırlar kaldırıldı. Buffer ve diğer eksik env değişkenleri eklendi.

## 2026-02-23 — Admin Panel Kod Kalitesi Refaktörü
- **`static/admin.css` (YENİ)**: Tüm stiller ayrı dosyaya taşındı. CSS değişkenleri (renk, spacing, radius) ile tema yönetimi; utility sınıfları (`.u-mt-12`, `.u-mt-16`, `.u-mt-20`, `.subsection-title`, `.card-note`, `.status-badge`, `.visually-hidden`, `.hidden`); provider badge modifer'ları (`.provider-badge--speechmatics`, `--openai`, `--gemini`, `--groq`).
- **`static/admin.html`**: Inline `<style>` kaldırıldı, `<link rel="stylesheet" href="/static/admin.css">` eklendi. Inline `style=""` kullanımları class'lara taşındı. Sekmeler için ARIA eklendi: `role="tablist"`, `role="tab"`, `aria-selected`, `aria-controls`, `role="tabpanel"`, `aria-labelledby`, `aria-hidden`. Paneller `<section>` ve anlamlı etiketlerle sarmalandı. TTS panelinde Deepgram bölümü kartın içine alındı (STT ile aynı yapı). Boş label erişilebilirlik için `<span class="visually-hidden">Boş</span>` kullanıldı. Butonlara `type="button"` eklendi.
- **`static/admin.js`**: Sekme değişiminde `aria-selected` ve `aria-hidden` güncelleniyor. TTS özel ses alanı göster/gizle `hidden` class ile yapılıyor.

## 2026-02-23 — LLM Provider Sadeleştirme (Anthropic & OpenAI-Compatible Kaldırıldı)
- **Anthropic ve OpenAI-Compatible provider'ları kaldırıldı.** Artık desteklenen LLM provider'lar: `openai`, `gemini`, `gemini_live`, `groq`.
- **`providers/llm_factory.py`**: `_create_anthropic_llm`, `_create_openai_compatible_llm` ve ilgili `create_async_client` dalları silindi. `VALID_LLM_PROVIDERS` güncellendi.
- **`config.py`**: `LLMConfig`'ten `anthropic_api_key` ve `base_url` alanları kaldırıldı.
- **`config_manager.py`**: `ANTHROPIC_API_KEY` ve `LLM_BASE_URL` env eşlemesi kaldırıldı.
- **`live_config.py`**: `VALID_LLM_PROVIDERS` ve `_RECREATE_FIELDS` sadeleştirildi.
- **`.env.example`**: Anthropic ve OpenAI-Compatible ile ilgili değişkenler ve açıklamalar kaldırıldı.
- **Admin Panel (`admin.html`, `admin.js`)**: Anthropic ve OpenAI-Compatible seçenekleri, API key/model alanları ve kaydetme mantığı kaldırıldı.
- **`requirements.txt`**: `pipecat-ai` extra'larından `anthropic` çıkarıldı.

## 2026-02-22 — STT Multi-Provider & Speechmatics Entegrasyonu
- **`providers/stt_factory.py` (YENİ Özellik)**: STT pipeline'ı için `speechmatics` provider desteği eklendi.
  - `speechmatics`: SpeechmaticsSTTService (Turkish için en yüksek doğruluk)
  - `turn_detection_mode` (EXTERNAL/SMART_TURN/ADAPTIVE), `enable_partials`, `max_delay` desteği admin panele taşındı.
- Admin panelinde STT için yeni arayüzler ve modeller eklendi (Groq Llama grubu ve Google Gemini 2.5 Flash-Lite dahil).

## 2026-02-22 — LLM Multi-Provider Desteği

### 🤖 LLM Multi-Provider (Restart Gerekmez)
- **`providers/llm_factory.py` (YENİ)**: STT/TTS factory pattern ile aynı mimari — LLM servisini provider'a göre oluşturan fabrika.
  - `openai`: OpenAILLMService — standart ve fine-tuned modeller (`ft:...`) desteklenir
  - `gemini`: GoogleLLMService — Gemini 2.5 Flash, 2.5 Pro, 2.0 Flash, 1.5 serisi
  - `anthropic`: AnthropicLLMService — Claude 3.5 Haiku/Sonnet, Opus 4.5
  - `groq`: GroqLLMService — Llama 3.3 70B / 3.1 8B / Mixtral 8x7B / Gemma2 9B / Llama 4; fine-tuned LoRA (Enterprise)
  - `openai_compatible`: custom `base_url` ile Ollama, LM Studio, vLLM, vb.
- **`providers/llm_switcher.py` (YENİ)**: `LLMServiceProxy` — STT/TTSServiceProxy ile aynı hot-swap pattern. Admin panelden provider değiştirildiğinde yeni LLM instance oluşturup çalışan pipeline'a enjekte eder; başarısız olursa rollback.
- **`config.py` güncellendi**: `LLMConfig`'e `provider`, `gemini_api_key`, `anthropic_api_key`, `base_url` alanları eklendi.
- **`config_manager.py` güncellendi**: `LLM_PROVIDER`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `LLM_BASE_URL` env mapping'leri eklendi.
- **`bot_runner.py` güncellendi**: OpenAI hardcode kaldırıldı. LLM artık factory'den oluşturuluyor; proxy içinde pipeline'a ekleniyor.
- **`live_config.py` güncellendi**: `_apply_llm()` multi-provider. Provider swap → `switch_provider()`, key/model değişimi → `recreate_current()` ile hot-reload.
- **`routes/context.py` güncellendi**: `set_llm_proxy` / `get_llm_proxy` eklendi.
- **`requirements.txt` güncellendi**: `pipecat-ai[google,anthropic]` extra'ları eklendi.
- **`.env.example` güncellendi**: `LLM_PROVIDER`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `LLM_BASE_URL` eklendi.
- **Admin Panel (`admin.html` + `admin.js`)**: LLM sekmesi provider dropdown'lu multi-panel haline getirildi. Her provider kendi API key / model seçici alanına sahip. Fine-tuned model için "Özel" seçeneği.
- **Artık restart gerektirmeyen**: LLM provider geçişi, API key değişimi, model değişimi.
- **Hâlâ restart gerektiren**: Audio sample rate, kaynak/hedef dil.

## 2026-02-11 — Admin Panel Düzeltmeleri & Güvenlik Güncellemesi


### 🛠️ Admin Panel ve Sistem Düzeltmeleri
- **AIC Toggle:** Config ayarına (`aic_enabled`) göre devreye girme/çıkma düzeltildi.
- **Provider Hot-Swap (Kritik):** Geçişlerde yaşanan donma sorunu, eski servise `CancelFrame` gönderilmeden önce pipeline bağlantısının (`_next`) kesilmesiyle çözüldü.
- **Cinsiyet Seçimi:** Admin panele Erkek/Kadın seçimi eklendi, arka planda doğru `voice_id` kullanımı sağlandı.
- **Runtime Config:** Audio/LiveKit gibi restart gerektiren ayarların runtime'da değişmesi engellendi.
- **STT Recreate:** Deepgram/Gladia parametre değişikliklerinde servis otomatik yenileniyor.

### 🔒 Güvenlik (PyJWT Geçişi)
- `python-jose` kütüphanesi, güvenlik açığı (CVE-2024-33663) nedeniyle **PyJWT** ile değiştirildi.
- `requirements.txt` güncellendi.
- `auth.py` refactor edildi.

### 📚 Dokümantasyon
- **README.md:** Proje kurulum ve kullanım kılavuzu tamamen yenilendi.
- **.env.example:** Örnek yapılandırma şablonu eklendi.

## 2026-02-11 — Restart'sız Provider Hot-Swap

### 🔄 Provider Hot-Swap (Restart Gerekmez)
- **STTServiceProxy** (`providers/stt_switcher.py`): Pipeline'daki STT servisini proxy pattern ile sarıyor. Admin panelden provider değiştirildiğinde yeni servis instance'ı oluşturup mevcut olanla değiştiriyor — restart gerekmez.
- **TTSServiceProxy** (`providers/tts_switcher.py`): Aynı proxy pattern TTS için. ElevenLabs ↔ Deepgram arası canlı geçiş.
- **`live_config.py` güncelleme**: Provider, API key ve model değişikliklerinde proxy üzerinden `switch_provider()` veya `recreate_current()` çağrılıyor.
- **`bot_runner.py` güncelleme**: STT/TTS servisleri artık proxy wrapper içinde pipeline'a yerleştiriliyor. Proxy ve aiohttp session global olarak live-config'e açık.
- **Artık restart gerektirmeyen alanlar**: STT/TTS provider değişimi, STT/TTS API key değişimi, STT/TTS model değişimi.
- **Hâlâ restart gerektiren**: Audio sample rate, LiveKit bağlantı bilgileri, kaynak/hedef dil.

## 2026-02-11 — Güvenlik, Çoklu Ses & Canlı Config Hot-Reload

### 🔒 Güvenlik
- **Sayfa Koruma Middleware**: `AuthPageMiddleware` eklendi — `/client`, `/client-controls`, `/admin` sayfaları sunucu tarafında JWT cookie kontrolü ile korunuyor. Login olmayan kullanıcılar `/login`'e yönlendiriliyor.
- **Brute-force Koruması**: `LoginRateLimiter` eklendi (`auth.py`) — IP bazlı 5 yanlış deneme sonrası 24 saat hesap kilitleme. Kalan deneme sayısı ve kilit süresi kullanıcıya gösteriliyor (HTTP 429).
- **Cookie Tabanlı Auth**: Login başarılı olduğunda `access_token` cookie'si set ediliyor (`login.html`), çıkışta siliniyor (`admin.js`).

### 🎙️ Çoklu Konuşmacı TTS
- **3 Voice ID desteği**: `config.py` TTSConfig'e `voice_id_male` (Adam: `pNInz6obpgDQGcFmaJgB`) ve `voice_id_female` (Alice: `Xb7hH8MSUJpSbSDYk0k2`) eklendi.
- **Admin Panel**: TTS sekmesine "Erkek Yedek Ses" ve "Kadın Yedek Ses" input alanları eklendi.
- **Config Manager**: `ELEVENLABS_VOICE_ID_MALE`, `ELEVENLABS_VOICE_ID_FEMALE` .env mapping'leri eklendi.

### ⚡ Canlı Config Hot-Reload
- **`live_config.py` (YENİ)**: Admin panelden yapılan değişiklikleri yayını durdurmadan canlı pipeline'a uygulayan modül.
- **Canlı değişen ayarlar** (restart gerekmez):
  - TTS: voice_id, speed, stability, similarity_boost (`TTSUpdateSettingsFrame`)
  - STT: language, VAD parametreleri (`STTUpdateSettingsFrame`)
  - LLM: model, api_key, system_prompt (direkt attribute güncelleme)
  - Buffer: Tüm 6 parametre (flush_timeout, min_words, min_sentences, max_words)
  - Genel: target_latency_ms, log_level
- **Admin Panel UX**: Kaydet sonrası toast bildirimi "✅ Canlı uygulandı" veya "restart gerektirir" şeklinde ayrıntılı geri bildirim gösteriyor.
- **bot_runner.py**: Pipeline oluşturulduktan sonra `register_services()` ile servisler kaydediliyor. PUT endpoint `apply_live_config()` çağırıyor.

## 2026-02-11 — Sunucu Ortamı, Admin Panel & Multi-Provider
- **JWT Login Sistemi**: `auth.py` – 24 saat geçerli JWT token, bcrypt veya plaintext şifre desteği. `/login` sayfası ve `/api/login` endpoint'i.
- **Admin Yapılandırma Paneli**: `/admin` – Tabbed arayüz (STT, TTS, LLM, Audio, Genel). API key maskeleme, slider'lar, toggle switch'ler.
- **Config Manager**: `config_manager.py` – `.env` dosyasına CRUD işlemleri, hassas alan maskeleme, çalışma zamanı ortam değişkeni güncelleme.
- **Multi-Provider STT**: ElevenLabs (varsayılan), Deepgram (Nova 3, $200 ücretsiz), Gladia – fabrika deseni (`providers/stt_factory.py`).
- **Multi-Provider TTS**: ElevenLabs (varsayılan), Deepgram Aura – fabrika deseni (`providers/tts_factory.py`).
- **Config.py Güncelleme**: STT/TTS `provider` alanları + tüm değerler `.env`'den okunur. Deepgram/Gladia API key ve model alanları eklendi.
- **Bot Runner**: Doğrudan ElevenLabs import'ları kaldırılıp fabrika deseniyle değiştirildi. Auth, config API, root redirect endpoint'leri eklendi.
- **Requirements**: `pipecat-ai[deepgram,gladia]`, `python-jose[cryptography]`, `passlib[bcrypt]` eklendi.
- **.env**: `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `JWT_SECRET_KEY`, `STT_PROVIDER`, `TTS_PROVIDER`, `DEEPGRAM_API_KEY`, `GLADIA_API_KEY` eklendi.

## 2026-02-06
- **Speed Kontrolü**: Arayüzden TTS konuşma hızı değiştirilebilir (0.8x – 1.1x). TTSUpdateSettingsFrame + doğrudan fallback desteği.
- **Buffer Temizleme**: Aktif LLM çağrılarını iptal eder, input buffer ve TTS kuyruğunu sıfırlar; geçmiş korunur.
- **Tam Sıfırlama (Reset All)**: Buffer + LLM geçmişi + kaynak metin geçmişi dahil her şeyi sıfırlar. Onay penceresi ile tetiklenir.
- **Gürültü Giderici Toggle**: AIC Filter (ai-coustics SDK) opsiyonel destek eklendi; kurulu değilse RNNoise fallback. Arayüzden açılıp kapatılabilir.
- **Kontrol Paneli UI**: `static/controls.js` — sabit konum kontrol paneli. HTTP API (`/api/control`) + WebRTC data channel üzerinden çalışır.
- **Control Processor**: `processors/control_processor.py` — pipeline'a eklenen FrameProcessor; speed, buffer, reset ve filtre mesajlarını işler.
- **AIC Debug Wrapper**: `processors/aic_debug_wrapper.py` — orijinal/filtrelenmiş ses kaydı + gain compensation desteği.
- **Kontrol panelli sayfa**: `/client-controls` endpoint'i ile kontroller otomatik yüklenir.
- `requirements.txt` güncellendi: `aic-sdk`, `numpy` eklendi.

## 2026-02-04
- STT duraksamalarında erken cümle kapanmasını azaltan buffer mantığı eklendi.
- Ünvan, bağlaç ve kısaltma bitişlerinde bekleme davranışı iyileştirildi.
- SRT örneklerine göre devam/ünvan/kısaltma sözlükleri genişletildi.
- Dinamik timeout ve timeout flush eşikleri eklendi.
- Context aggregator eklendi; asistan metni TTSTextFrame ile UI’da görünür hale getirildi.
- Ctrl+C kapanışında MP3 streaming sırasında oluşan BrokenPipe hatası bastırıldı.
