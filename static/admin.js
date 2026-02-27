(function () {
    'use strict';

    // ============================================================
    // Auth helpers
    // ============================================================
    function getCookie(name) {
        var match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? decodeURIComponent(match[2]) : '';
    }

    var token = localStorage.getItem('auth_token');
    if (!token) {
        var cookieToken = getCookie('access_token');
        if (cookieToken) {
            token = cookieToken;
            localStorage.setItem('auth_token', token);
        }
    }
    if (!token) {
        window.location.href = '/login';
        return;
    }

    function authHeaders() {
        var headers = { 'Content-Type': 'application/json' };
        if (token) headers.Authorization = 'Bearer ' + token;
        return headers;
    }

    function handleAuthError(r) {
        if (r.status === 401) {
            localStorage.removeItem('auth_token');
            fetch('/api/logout', { method: 'POST' }).finally(function () {
                window.location.href = '/login';
            });
            return true;
        }
        return false;
    }

    // ============================================================
    // Ortak fetch yardımcısı
    // ============================================================
    // Auth header'larını ekler, 401 durumunda logout yapar ve JSON döner.
    // options.body varsa Content-Type otomatik eklenir.
    // Dönen Promise: başarıda parsed JSON objesi, 401/hata durumunda null.
    function apiFetch(url, options) {
        var opts = options || {};
        var method = opts.method || 'GET';
        var headers = authHeaders();
        if (opts.headers) {
            Object.keys(opts.headers).forEach(function (k) {
                headers[k] = opts.headers[k];
            });
        }
        return fetch(url, {
            method: method,
            headers: headers,
            body: opts.body !== undefined ? opts.body : undefined
        }).then(function (r) {
            if (handleAuthError(r)) return null;
            return r.json();
        });
    }

    // ============================================================
    // Tab switching
    // ============================================================
    var tabBtns = document.querySelectorAll('.tab-btn');

    tabBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            var tabId = btn.getAttribute('data-tab');
            var panels = document.querySelectorAll('.tab-panel');
            tabBtns.forEach(function (b) {
                b.classList.remove('active');
                b.setAttribute('aria-selected', 'false');
            });
            panels.forEach(function (p) {
                p.classList.remove('active');
                p.setAttribute('aria-hidden', 'true');
            });
            btn.classList.add('active');
            btn.setAttribute('aria-selected', 'true');
            var panel = document.getElementById('panel-' + tabId);
            if (panel) {
                panel.classList.add('active');
                panel.setAttribute('aria-hidden', 'false');
            }
        });
    });

    // ============================================================
    // Slider value display
    // ============================================================
    var sliders = [
        ['vad_silence_threshold', 'vad_silence_threshold_val'],
        ['vad_threshold', 'vad_threshold_val'],
        ['tts_speed', 'tts_speed_val'],
        ['tts_stability', 'tts_stability_val'],
        ['tts_similarity_boost', 'tts_similarity_boost_val'],
        ['tts_style', 'tts_style_val'],
        ['stt_gladia_endpointing', 'stt_gladia_endpointing_val'],
        ['buffer_flush_timeout_secs', 'buffer_flush_timeout_secs_val'],
        ['verifier_timeout', 'verifier_timeout_val'],
    ];

    sliders.forEach(function (pair) {
        var slider = document.getElementById(pair[0]);
        var display = document.getElementById(pair[1]);
        if (slider && display) {
            slider.addEventListener('input', function () {
                display.textContent = slider.value;
            });
        }
    });

    // ============================================================
    // Provider switching
    // ============================================================

    // Genel provider değişim fonksiyonu: type = 'stt' | 'tts' | 'llm'
    // providers: visible/gizlenecek provider isimlerinin dizisi
    window.onProviderChange = function (type, providers) {
        var provider = document.getElementById(type + '_provider').value;
        providers.forEach(function (p) {
            var section = document.getElementById(type + '-' + p);
            if (section) {
                section.classList.toggle('visible', p === provider);
            }
        });

        // STT'ye özel ek mantık
        if (type === 'stt') {
            // ElevenLabs ve Gemini Live custom vocabulary desteklemiyor — toggle'ı gizle
            var vocabRow = document.getElementById('stt_vocab_toggle_row');
            if (vocabRow) {
                vocabRow.style.display = (provider === 'elevenlabs' || provider === 'gemini_live') ? 'none' : '';
            }
            // Vocab panelinde aktif provider'ı vurgula
            highlightActiveVocabProvider(provider);
        }

        // LLM'ye özel ek mantık
        if (type === 'llm') {
            syncLLMModel();
        }
    };

    // Geriye dönük uyumluluk için eski isimleri koru (populateForm bunları çağırıyor)
    window.onSTTProviderChange = function () {
        window.onProviderChange('stt', ['elevenlabs', 'deepgram', 'gladia', 'speechmatics', 'gemini_live']);
    };

    window.onTTSProviderChange = function () {
        window.onProviderChange('tts', ['elevenlabs', 'deepgram']);
    };

    window.onLLMProviderChange = function () {
        window.onProviderChange('llm', ['openai', 'gemini', 'groq']);
    };

    // Sync hidden llm_model field from the active provider's text input
    window.syncLLMModel = function () {
        var provider = (document.getElementById('llm_provider') || {}).value || 'openai';
        var modelVal = '';
        // Map each provider to its model input element id
        var inputId = 'llm_model_' + provider;
        var inp = document.getElementById(inputId);
        if (inp) modelVal = inp.value;
        var hiddenModel = document.getElementById('llm_model');
        if (hiddenModel) hiddenModel.value = modelVal;
    };

    // LLM Sub-tab switching
    window.switchLlmSubTab = function (tabId) {
        // Handle buttons
        document.getElementById('btn-llm-translator').style.borderBottom = 'none';
        document.getElementById('btn-llm-translator').style.color = '#64748b';
        document.getElementById('btn-llm-verifier').style.borderBottom = 'none';
        document.getElementById('btn-llm-verifier').style.color = '#64748b';

        var activeBtn = document.getElementById('btn-llm-' + tabId);
        if (activeBtn) {
            activeBtn.style.borderBottom = '2px solid #3b82f6';
            activeBtn.style.color = '#3b82f6';
        }

        // Handle sections
        document.getElementById('section-llm-translator').style.display = (tabId === 'translator') ? 'block' : 'none';
        document.getElementById('section-llm-verifier').style.display = (tabId === 'verifier') ? 'block' : 'none';
    };

    // Gemini STT model select ↔ custom input sync
    window.onGeminiSTTModelChange = function () {
        var sel = document.getElementById('stt_gemini_stt_model_select');
        var inp = document.getElementById('stt_gemini_stt_model');
        if (!sel || !inp) return;
        if (sel.value === 'custom') {
            inp.classList.remove('hidden');
        } else {
            inp.classList.add('hidden');
            inp.value = sel.value;
        }
    };

    // Gemini domain kelime listesi — dosyadan yükle (.txt veya .json)
    window.handleGeminiVocabUpload = function (inputElem) {
        if (!inputElem.files || inputElem.files.length === 0) return;
        var file = inputElem.files[0];
        if (file.size > 2 * 1024 * 1024) {
            showToast('Dosya çok büyük (Max 2MB)', 'error');
            return;
        }
        var reader = new FileReader();
        reader.onload = function (e) {
            var content = e.target.result;
            var words = [];
            if (file.name.toLowerCase().endsWith('.json')) {
                try {
                    var obj = JSON.parse(content);
                    if (Array.isArray(obj)) {
                        obj.forEach(function (item) {
                            if (typeof item === 'string') words.push(item.trim());
                            else if (item && (item.word || item.content)) words.push((item.word || item.content).trim());
                        });
                    } else if (typeof obj === 'object') {
                        Object.keys(obj).forEach(function (key) { words.push(key.trim()); });
                    }
                } catch (err) {
                    showToast('Hatalı JSON formatı', 'error');
                    inputElem.value = '';
                    return;
                }
            } else {
                // .txt: virgülle veya satır satır ayrılmış kelimeler
                words = content.split(/[\n,]+/).map(function (w) { return w.trim(); }).filter(function (w) { return w.length > 0; });
            }
            var ta = document.getElementById('stt_gemini_stt_domain_vocabulary');
            if (ta) {
                ta.value = words.join(', ');
                showToast(file.name + ' yüklendi (' + words.length + ' kelime). Kaydetmeyi unutmayın.', 'success');
            }
            inputElem.value = '';
        };
        reader.onerror = function () { showToast('Dosya okuma hatası', 'error'); };
        reader.readAsText(file, 'UTF-8');
    };

    window.toggleCustomVocabInput = function () {
        var enabled = document.getElementById('stt_enable_custom_vocabulary').checked;
        var notice = document.getElementById('vocab_disabled_notice');
        if (notice) {
            notice.style.display = enabled ? 'none' : 'block';
        }
    };

    // ── Kelime sayacı (vocab textarea'ları için) ──────────────────
    window.updateVocabCount = function (textareaId, counterId, maxCount) {
        var ta = document.getElementById(textareaId);
        var counter = document.getElementById(counterId);
        if (!ta || !counter) return;
        var lines = ta.value.split('\n').filter(function (l) {
            var word = l.split('|')[0].trim().replace(/,$/, '');
            return word.length > 0;
        });
        var count = lines.length;
        counter.textContent = count + ' / ' + maxCount;
        counter.style.color = count > maxCount ? '#ef4444' : count > maxCount * 0.85 ? '#f59e0b' : '#6b7280';
    };

    // ── Aktif provider'ı vocab panelinde vurgula ──────────────────
    window.highlightActiveVocabProvider = function (provider) {
        var providers = ['speechmatics', 'gladia', 'deepgram'];
        providers.forEach(function (p) {
            var section = document.getElementById('vocab-section-' + p);
            var badge = document.getElementById('vocab-badge-' + p);
            if (!section || !badge) return;
            if (p === provider) {
                section.style.outline = '2px solid #6366f1';
                section.style.borderRadius = '8px';
                section.style.padding = '8px';
                badge.title = 'Şu an aktif provider';
                if (!badge.querySelector('.active-indicator')) {
                    var dot = document.createElement('span');
                    dot.className = 'active-indicator';
                    dot.textContent = ' ● AKTİF';
                    dot.style.cssText = 'color:#6366f1;font-size:10px;font-weight:700;margin-left:6px;';
                    badge.appendChild(dot);
                }
            } else {
                section.style.outline = '';
                section.style.borderRadius = '';
                section.style.padding = '';
                var dot = badge.querySelector('.active-indicator');
                if (dot) badge.removeChild(dot);
            }
        });
    };

    window.toggleVerifierSettings = function () {
        var enabled = document.getElementById('verifier_enabled').checked;
        var container = document.getElementById('verifier_settings_container');
        if (container) {
            container.style.display = enabled ? 'block' : 'none';
        }
    };

    // ============================================================
    // Load config from server
    // ============================================================
    window.loadConfig = function () {
        apiFetch('/api/config')
            .then(function (cfg) {
                if (!cfg) return;
                populateForm(cfg);
            })
            .catch(function (err) {
                showToast('Config yüklenemedi: ' + err.message, 'error');
            });
    };

    var initialConfig = {};

    function populateForm(cfg) {
        // STT
        if (cfg.stt) {
            setVal('stt_provider', cfg.stt.provider || 'elevenlabs');
            setVal('stt_language', cfg.stt.language);
            setVal('stt_api_key', cfg.stt.api_key);
            setSelectWithCustom('stt_model', 'stt_model_custom', cfg.stt.model);
            setVal('stt_deepgram_api_key', cfg.stt.deepgram_api_key);
            setSelectWithCustom('stt_deepgram_model', 'stt_deepgram_model_custom', cfg.stt.deepgram_model);
            setVal('stt_gladia_api_key', cfg.stt.gladia_api_key);
            setSelectWithCustom('stt_gladia_model', 'stt_gladia_model_custom', cfg.stt.gladia_model);
            // Deepgram-specific
            setChecked('stt_deepgram_smart_format', cfg.stt.deepgram_smart_format);
            setChecked('stt_deepgram_punctuate', cfg.stt.deepgram_punctuate);
            setChecked('stt_deepgram_no_delay', cfg.stt.deepgram_no_delay);
            setVal('stt_deepgram_utterance_end_ms', cfg.stt.deepgram_utterance_end_ms);

            // Custom Vocabulary
            setChecked('stt_enable_custom_vocabulary', cfg.stt.enable_custom_vocabulary);
            setVal('stt_deepgram_vocabulary', cfg.stt.stt_deepgram_vocabulary);
            setVal('stt_gladia_vocabulary', cfg.stt.stt_gladia_vocabulary);
            setVal('stt_speechmatics_vocabulary', cfg.stt.stt_speechmatics_vocabulary);
            toggleCustomVocabInput();
            // Kelime sayaçlarını güncelle
            updateVocabCount('stt_deepgram_vocabulary', 'vocab_count_deepgram', 100);
            updateVocabCount('stt_gladia_vocabulary', 'vocab_count_gladia', 250);
            updateVocabCount('stt_speechmatics_vocabulary', 'vocab_count_speechmatics', 1000);
            // Gladia intensity
            var intensity = cfg.stt.gladia_vocab_intensity != null ? cfg.stt.gladia_vocab_intensity : 0.5;
            setSlider('stt_gladia_vocab_intensity', intensity);
            var intensityVal = document.getElementById('gladia_intensity_val');
            if (intensityVal) intensityVal.textContent = parseFloat(intensity).toFixed(2);
            // Aktif provider vurgula
            highlightActiveVocabProvider(cfg.stt.provider || 'elevenlabs');

            // Gladia-specific
            setSlider('stt_gladia_endpointing', cfg.stt.gladia_endpointing);
            setVal('stt_gladia_max_duration', cfg.stt.gladia_max_duration);
            setChecked('stt_gladia_audio_enhancer', cfg.stt.gladia_audio_enhancer);
            setChecked('stt_gladia_code_switching', cfg.stt.gladia_code_switching);
            // Speechmatics-specific
            setVal('stt_speechmatics_api_key', cfg.stt.speechmatics_api_key);
            setVal('stt_speechmatics_language', cfg.stt.speechmatics_language);
            setVal('stt_speechmatics_max_delay', cfg.stt.speechmatics_max_delay);
            setVal('stt_speechmatics_turn_detection', cfg.stt.speechmatics_turn_detection || 'external');
            setChecked('stt_speechmatics_enable_partials', cfg.stt.speechmatics_enable_partials !== false);
            // Gemini Live STT-specific
            var geminiModel = cfg.stt.gemini_stt_model || 'gemini-2.5-flash-native-audio-preview-12-2025';
            var geminiSel = document.getElementById('stt_gemini_stt_model_select');
            var geminiInp = document.getElementById('stt_gemini_stt_model');
            if (geminiSel && geminiInp) {
                var knownModels = Array.from(geminiSel.options).map(function (o) { return o.value; }).filter(function (v) { return v !== 'custom'; });
                if (knownModels.indexOf(geminiModel) !== -1) {
                    geminiSel.value = geminiModel;
                    geminiInp.value = geminiModel;
                    geminiInp.classList.add('hidden');
                } else {
                    geminiSel.value = 'custom';
                    geminiInp.value = geminiModel;
                    geminiInp.classList.remove('hidden');
                }
            }
            setVal('stt_gemini_api_key', cfg.stt.gemini_api_key);
            setVal('stt_gemini_stt_silence_duration_ms', cfg.stt.gemini_stt_silence_duration_ms != null ? cfg.stt.gemini_stt_silence_duration_ms : 400);
            setVal('stt_gemini_stt_end_sensitivity', cfg.stt.gemini_stt_end_sensitivity || 'HIGH');
            setVal('stt_gemini_stt_start_sensitivity', cfg.stt.gemini_stt_start_sensitivity || 'HIGH');
            if (cfg.stt.gemini_stt_prefix_padding_ms != null) setVal('stt_gemini_stt_prefix_padding_ms', cfg.stt.gemini_stt_prefix_padding_ms);
            setVal('stt_gemini_stt_system_instruction', cfg.stt.gemini_stt_system_instruction || '');
            setChecked('stt_gemini_stt_context_compression', cfg.stt.gemini_stt_context_compression !== false);
            setChecked('stt_gemini_stt_punctuation_mode', cfg.stt.gemini_stt_punctuation_mode !== false);
            setVal('stt_gemini_stt_domain_vocabulary', cfg.stt.gemini_stt_domain_vocabulary || '');
            // VAD
            setSlider('vad_silence_threshold', cfg.stt.vad_silence_threshold);
            setSlider('vad_threshold', cfg.stt.vad_threshold);
            setVal('min_speech_duration_ms', cfg.stt.min_speech_duration_ms);
            setVal('min_silence_duration_ms', cfg.stt.min_silence_duration_ms);
            onSTTProviderChange();
        }

        // TTS
        if (cfg.tts) {
            setVal('tts_provider', cfg.tts.provider || 'elevenlabs');
            setVal('tts_api_key', cfg.tts.api_key);

            // Gender logic
            var currentVid = cfg.tts.voice_id;
            var maleVid = cfg.tts.voice_id_male;
            var femaleVid = cfg.tts.voice_id_female;

            setVal('tts_voice_id', currentVid);
            setVal('tts_voice_id_male', maleVid);
            setVal('tts_voice_id_female', femaleVid);

            var genderSelect = document.getElementById('tts_voice_gender');
            if (currentVid === maleVid) {
                genderSelect.value = 'male';
            } else if (currentVid === femaleVid) {
                genderSelect.value = 'female';
            } else {
                genderSelect.value = 'custom';
                setVal('tts_voice_id_custom', currentVid);
            }
            // Trigger UI update
            if (window.toggleVoiceIdInput) window.toggleVoiceIdInput();

            setVal('tts_model', cfg.tts.model);
            setSlider('tts_speed', cfg.tts.speed);
            setSlider('tts_stability', cfg.tts.stability);
            setSlider('tts_similarity_boost', cfg.tts.similarity_boost);

            setVal('tts_deepgram_api_key', cfg.tts.deepgram_api_key);
            setVal('tts_deepgram_model', cfg.tts.deepgram_model);
            // ElevenLabs-specific
            setSlider('tts_style', cfg.tts.style);
            setChecked('tts_use_speaker_boost', cfg.tts.use_speaker_boost);
            setVal('tts_apply_text_normalization', cfg.tts.apply_text_normalization);
            // Deepgram-specific
            setVal('tts_deepgram_encoding', cfg.tts.deepgram_encoding);
            onTTSProviderChange();
        }

        // LLM
        if (cfg.llm) {
            var llmProvider = cfg.llm.provider || 'openai';
            setVal('llm_provider', llmProvider);

            // API keys
            setVal('llm_api_key', cfg.llm.api_key);
            setVal('llm_gemini_api_key', cfg.llm.gemini_api_key);
            setVal('llm_groq_api_key', cfg.llm.groq_api_key);

            // Set model in all provider text inputs (each gets the same saved model)
            var model = cfg.llm.model || '';
            setVal('llm_model_openai', model);
            setVal('llm_model_gemini', model);
            setVal('llm_model_groq', model);

            setVal('llm_system_prompt', cfg.llm.system_prompt);
            onLLMProviderChange(); // trigger UI show/hide + syncLLMModel
        }

        // Verifier
        if (cfg.verifier) {
            setChecked('verifier_enabled', cfg.verifier.enabled);
            setVal('verifier_provider', cfg.verifier.provider || 'groq');
            setVal('verifier_model', cfg.verifier.model);
            setSlider('verifier_timeout', cfg.verifier.timeout != null ? cfg.verifier.timeout : 3.0);
            setVal('verifier_prompt', cfg.verifier.prompt);
            toggleVerifierSettings();
        }

        // Audio
        if (cfg.audio) {
            setChecked('audio_aic_enabled', cfg.audio.aic_enabled);
            setChecked('audio_aic_gain_compensation', cfg.audio.aic_gain_compensation);
            setChecked('audio_debug_audio', cfg.audio.debug_audio);
            setVal('audio_aic_license_key', cfg.audio.aic_license_key);
            setVal('audio_aic_model_id', cfg.audio.aic_model_id);
            setVal('audio_sample_rate', cfg.audio.sample_rate);
            setVal('audio_output_sample_rate', cfg.audio.output_sample_rate);
            setVal('audio_channels', cfg.audio.channels);
            setVal('audio_chunk_size_ms', cfg.audio.chunk_size_ms);
        }

        // General
        if (cfg.general) {
            setVal('general_source_language', cfg.general.source_language);
            setVal('general_target_language', cfg.general.target_language);
            setVal('general_log_level', cfg.general.log_level);
            setVal('general_target_latency_ms', cfg.general.target_latency_ms);
        }

        // Buffer
        if (cfg.buffer) {
            setSlider('buffer_flush_timeout_secs', cfg.buffer.flush_timeout_secs);
            setVal('buffer_min_words_long', cfg.buffer.min_words_long);
            setVal('buffer_min_words_with_punct', cfg.buffer.min_words_with_punct);
            setVal('buffer_min_sentences', cfg.buffer.min_sentences);
            setVal('buffer_min_words_timeout', cfg.buffer.min_words_timeout);
            setVal('buffer_max_buffer_words', cfg.buffer.max_buffer_words);
        }

        refreshInitialConfig();
    }

    function setSelectWithCustom(selectId, inputId, value) {
        var select = document.getElementById(selectId);
        var customInput = document.getElementById(inputId);
        if (!select || value === undefined || value === null) return;

        var optionExists = false;
        for (var i = 0; i < select.options.length; i++) {
            if (select.options[i].value === value && value !== 'custom') {
                optionExists = true;
                break;
            }
        }

        if (optionExists) {
            select.value = value;
            if (customInput) customInput.classList.add('hidden');
        } else {
            select.value = 'custom';
            if (customInput) {
                customInput.value = value;
                customInput.classList.remove('hidden');
            }
        }
    }

    function getSelectWithCustom(selectId, inputId) {
        var select = document.getElementById(selectId);
        if (select && select.value === 'custom') {
            return getVal(inputId);
        }
        return getVal(selectId);
    }

    window.toggleCustomSTTModel = function (selectId, inputId) {
        var select = document.getElementById(selectId);
        var input = document.getElementById(inputId);
        if (select && input) {
            if (select.value === 'custom') {
                input.classList.remove('hidden');
            } else {
                input.classList.add('hidden');
            }
        }
    };

    function setVal(id, value) {
        var el = document.getElementById(id);
        if (el && value !== undefined && value !== null) {
            el.value = value;
        }
    }

    function setSlider(id, value) {
        var el = document.getElementById(id);
        var display = document.getElementById(id + '_val');
        if (el && value !== undefined && value !== null) {
            el.value = value;
            if (display) display.textContent = value;
        }
    }

    function setChecked(id, value) {
        var el = document.getElementById(id);
        if (el) el.checked = !!value;
    }

    // ============================================================
    // Save config section
    // ============================================================
    // STT vocab değişikliklerinde aktif oturumu kontrol et
    function _checkSessionBeforeSave(section, onProceed) {
        if (section !== 'stt') { onProceed(); return; }

        apiFetch('/api/session/status')
            .then(function (status) {
                if (status && status.session_busy) {
                    if (confirm('⚠️ Aktif bir oturum var. STT ayarları kaydedilirse servis kısa süreliğine yeniden başlatılır ve ses akışı kesilir.\n\nDevam edilsin mi?')) {
                        onProceed();
                    }
                } else {
                    onProceed();
                }
            })
            .catch(function () { onProceed(); }); // hata olursa sessizce devam et
    }

    window.saveSection = function (section) {
        var data = collectSectionData(section);
        if (!data) return;
        var filtered = filterChangedData(section, data);
        if (Object.keys(filtered).length === 0) {
            showToast('Değişiklik yok', 'success');
            return;
        }

        _checkSessionBeforeSave(section, function () {
            apiFetch('/api/config/' + section, {
                method: 'PUT',
                body: JSON.stringify(filtered)
            })
                .then(function (result) {
                    if (!result) return;
                    if (result.status === 'ok') {
                        var liveApplied = result.live_applied || [];
                        var liveSkipped = result.live_skipped || [];
                        var msg = '';
                        if (liveApplied.length > 0 && liveSkipped.length === 0) {
                            msg = '✅ Canlı uygulandı — yeniden başlatma gerekmez';
                        } else if (liveApplied.length > 0 && liveSkipped.length > 0) {
                            msg = '✅ ' + liveApplied.length + ' ayar canlı uygulandı — ' + liveSkipped.length + ' ayar restart gerektirir';
                        } else if (result.restart_required) {
                            msg = 'Kaydedildi — değişiklikler restart sonrası aktif olacak';
                        } else {
                            msg = 'Ayarlar kaydedildi';
                        }
                        showToast(msg, 'success');
                        applyInitialUpdate(section, filtered);
                    } else {
                        showToast('Hata: ' + (result.message || 'Bilinmeyen hata'), 'error');
                    }
                })
                .catch(function (err) {
                    showToast('Kayıt hatası: ' + err.message, 'error');
                });
        }); // _checkSessionBeforeSave
    };

    function refreshInitialConfig() {
        initialConfig = {
            stt: collectSectionData('stt'),
            tts: collectSectionData('tts'),
            llm: collectSectionData('llm'),
            verifier: collectSectionData('verifier'),
            audio: collectSectionData('audio'),
            general: collectSectionData('general'),

            buffer: collectSectionData('buffer')
        };
    }

    function applyInitialUpdate(section, data) {
        if (!initialConfig[section]) initialConfig[section] = {};
        Object.keys(data).forEach(function (key) {
            initialConfig[section][key] = data[key];
        });
    }

    function filterChangedData(section, data) {
        var base = initialConfig[section] || {};
        var out = {};
        Object.keys(data).forEach(function (key) {
            var value = data[key];
            if (typeof value === 'string' && value.indexOf('****') !== -1) return;
            if (!base.hasOwnProperty(key) || !valuesEqual(base[key], value)) {
                out[key] = value;
            }
        });
        return out;
    }

    function valuesEqual(a, b) {
        if (typeof a === 'number' && typeof b === 'number') {
            if (isNaN(a) && isNaN(b)) return true;
        }
        return a === b;
    }

    function collectSectionData(section) {
        var data = {};
        switch (section) {
            case 'stt':
                data.provider = getVal('stt_provider');
                data.language = getVal('stt_language');
                data.api_key = getVal('stt_api_key');
                data.model = getSelectWithCustom('stt_model', 'stt_model_custom');
                data.deepgram_api_key = getVal('stt_deepgram_api_key');
                data.deepgram_model = getSelectWithCustom('stt_deepgram_model', 'stt_deepgram_model_custom');
                data.gladia_api_key = getVal('stt_gladia_api_key');
                data.gladia_model = getSelectWithCustom('stt_gladia_model', 'stt_gladia_model_custom');
                data.vad_silence_threshold = parseFloat(getVal('vad_silence_threshold'));
                data.vad_threshold = parseFloat(getVal('vad_threshold'));
                data.min_speech_duration_ms = parseInt(getVal('min_speech_duration_ms'));
                data.min_silence_duration_ms = parseInt(getVal('min_silence_duration_ms'));
                // Deepgram-specific
                data.deepgram_smart_format = getChecked('stt_deepgram_smart_format');
                data.deepgram_punctuate = getChecked('stt_deepgram_punctuate');
                data.deepgram_no_delay = getChecked('stt_deepgram_no_delay');
                data.deepgram_utterance_end_ms = getVal('stt_deepgram_utterance_end_ms');

                data.enable_custom_vocabulary = getChecked('stt_enable_custom_vocabulary');
                data.stt_deepgram_vocabulary = getVal('stt_deepgram_vocabulary');
                data.stt_gladia_vocabulary = getVal('stt_gladia_vocabulary');
                data.stt_speechmatics_vocabulary = getVal('stt_speechmatics_vocabulary');
                data.gladia_vocab_intensity = parseFloat(getVal('stt_gladia_vocab_intensity') || '0.5');

                // Gladia-specific
                data.gladia_endpointing = parseFloat(getVal('stt_gladia_endpointing'));
                data.gladia_max_duration = parseInt(getVal('stt_gladia_max_duration'));
                data.gladia_audio_enhancer = getChecked('stt_gladia_audio_enhancer');
                data.gladia_code_switching = getChecked('stt_gladia_code_switching');
                // Speechmatics-specific
                data.speechmatics_api_key = getVal('stt_speechmatics_api_key');
                data.speechmatics_language = getVal('stt_speechmatics_language');
                data.speechmatics_max_delay = parseFloat(getVal('stt_speechmatics_max_delay'));
                data.speechmatics_turn_detection = getVal('stt_speechmatics_turn_detection');
                data.speechmatics_enable_partials = getChecked('stt_speechmatics_enable_partials');
                // Gemini Live STT-specific
                data.gemini_api_key = getVal('stt_gemini_api_key');
                // Model: from hidden text input (always kept in sync with select)
                var gSel = document.getElementById('stt_gemini_stt_model_select');
                var gInp = document.getElementById('stt_gemini_stt_model');
                data.gemini_stt_model = (gSel && gSel.value !== 'custom' ? gSel.value : null) || (gInp ? gInp.value : '') || 'gemini-2.5-flash-native-audio-preview-12-2025';
                data.gemini_stt_silence_duration_ms = parseInt(getVal('stt_gemini_stt_silence_duration_ms') || '400');
                data.gemini_stt_end_sensitivity = getVal('stt_gemini_stt_end_sensitivity') || 'HIGH';
                data.gemini_stt_start_sensitivity = getVal('stt_gemini_stt_start_sensitivity') || 'HIGH';
                var prefixPad = getVal('stt_gemini_stt_prefix_padding_ms');
                data.gemini_stt_prefix_padding_ms = prefixPad !== '' ? parseInt(prefixPad) : null;
                data.gemini_stt_system_instruction = getVal('stt_gemini_stt_system_instruction') || '';
                data.gemini_stt_context_compression = getChecked('stt_gemini_stt_context_compression');
                data.gemini_stt_punctuation_mode = getChecked('stt_gemini_stt_punctuation_mode');
                data.gemini_stt_domain_vocabulary = getVal('stt_gemini_stt_domain_vocabulary') || '';
                break;
            case 'tts':
                data.provider = getVal('tts_provider');
                data.api_key = getVal('tts_api_key');

                // Voice ID logic based on gender selector
                var gender = document.getElementById('tts_voice_gender').value;
                var maleVid = getVal('tts_voice_id_male');
                var femaleVid = getVal('tts_voice_id_female');
                var customVid = getVal('tts_voice_id_custom');

                if (gender === 'male') {
                    data.voice_id = maleVid;
                } else if (gender === 'female') {
                    data.voice_id = femaleVid;
                } else {
                    data.voice_id = customVid;
                }

                data.voice_id_male = maleVid;
                data.voice_id_female = femaleVid;
                data.model = getVal('tts_model');
                data.speed = parseFloat(getVal('tts_speed'));
                data.stability = parseFloat(getVal('tts_stability'));
                data.similarity_boost = parseFloat(getVal('tts_similarity_boost'));

                data.deepgram_api_key = getVal('tts_deepgram_api_key');
                data.deepgram_model = getVal('tts_deepgram_model');
                // ElevenLabs-specific
                data.style = parseFloat(getVal('tts_style'));
                data.use_speaker_boost = getChecked('tts_use_speaker_boost');
                data.apply_text_normalization = getVal('tts_apply_text_normalization');
                // Deepgram-specific
                data.deepgram_encoding = getVal('tts_deepgram_encoding');
                break;
            case 'llm':
                data.provider = getVal('llm_provider');
                syncLLMModel();
                data.model = getVal('llm_model');
                // API keys (send always, backend will skip masked)
                data.api_key = getVal('llm_api_key');
                data.gemini_api_key = getVal('llm_gemini_api_key');
                data.groq_api_key = getVal('llm_groq_api_key');
                data.system_prompt = getVal('llm_system_prompt');
                break;
            case 'verifier':
                data.enabled = getChecked('verifier_enabled');
                data.provider = getVal('verifier_provider');
                data.model = getVal('verifier_model');
                data.timeout = parseFloat(getVal('verifier_timeout'));
                data.prompt = getVal('verifier_prompt');
                break;
            case 'audio':
                data.aic_enabled = getChecked('audio_aic_enabled');
                data.aic_gain_compensation = getChecked('audio_aic_gain_compensation');
                data.debug_audio = getChecked('audio_debug_audio');
                data.aic_license_key = getVal('audio_aic_license_key');
                data.aic_model_id = getVal('audio_aic_model_id');
                data.sample_rate = parseInt(getVal('audio_sample_rate'));
                data.output_sample_rate = parseInt(getVal('audio_output_sample_rate'));
                data.channels = parseInt(getVal('audio_channels'));
                data.chunk_size_ms = parseInt(getVal('audio_chunk_size_ms'));
                break;
            case 'general':
                data.source_language = getVal('general_source_language');
                data.target_language = getVal('general_target_language');
                data.log_level = getVal('general_log_level');
                data.target_latency_ms = parseInt(getVal('general_target_latency_ms'));
                break;

            case 'buffer':
                data.flush_timeout_secs = parseFloat(getVal('buffer_flush_timeout_secs'));
                data.min_words_long = parseInt(getVal('buffer_min_words_long'));
                data.min_words_with_punct = parseInt(getVal('buffer_min_words_with_punct'));
                data.min_sentences = parseInt(getVal('buffer_min_sentences'));
                data.min_words_timeout = parseInt(getVal('buffer_min_words_timeout'));
                data.max_buffer_words = parseInt(getVal('buffer_max_buffer_words'));
                break;
        }
        return data;
    }

    function getVal(id) {
        var el = document.getElementById(id);
        return el ? el.value : '';
    }

    function getChecked(id) {
        var el = document.getElementById(id);
        return el ? el.checked : false;
    }

    // ============================================================
    // Toast notification
    // ============================================================
    var toastTimeout = null;

    window.showToast = function (message, type) {
        var toast = document.getElementById('toast');
        toast.textContent = message;
        toast.className = 'toast ' + (type || 'success');
        // Force reflow for animation
        toast.offsetHeight;
        toast.classList.add('visible');

        if (toastTimeout) clearTimeout(toastTimeout);
        toastTimeout = setTimeout(function () {
            toast.classList.remove('visible');
        }, type === 'error' ? 5000 : 3000);
    };

    // ============================================================
    // Logout
    // ============================================================
    document.getElementById('logoutBtn').addEventListener('click', function () {
        localStorage.removeItem('auth_token');
        fetch('/api/logout', { method: 'POST' }).finally(function () {
            window.location.href = '/login';
        });
    });

    // ============================================================
    // Reset to Defaults
    // ============================================================
    var resetDefaultsBtn = document.getElementById('resetDefaultsBtn');
    if (resetDefaultsBtn) {
        resetDefaultsBtn.addEventListener('click', function () {
            if (!confirm('Tüm ayarları (API Key, Şifre vb. HARİÇ) fabrika ayarlarına döndürmek istediğinize emin misiniz?')) {
                return;
            }

            resetDefaultsBtn.disabled = true;
            resetDefaultsBtn.textContent = '⏱️ Sıfırlanıyor...';

            apiFetch('/api/system/reset', { method: 'POST' })
                .then(function (result) {
                    if (!result) return;
                    if (result.status === 'ok') {
                        showToast(result.message, 'success');
                        setTimeout(function () {
                            window.location.reload();
                        }, 2000);
                    } else {
                        resetDefaultsBtn.disabled = false;
                        resetDefaultsBtn.textContent = '⚠️ Fabrika Ayarları';
                        showToast('Hata: ' + result.message, 'error');
                    }
                })
                .catch(function (err) {
                    resetDefaultsBtn.disabled = false;
                    resetDefaultsBtn.textContent = '⚠️ Fabrika Ayarları';
                    showToast('Hata: ' + err.message, 'error');
                });
        });
    }

    // ============================================================
    // MP3 Stream toggle
    // ============================================================
    var MP3_URL_KEY = 'mp3_stream_saved_url';

    window.toggleMp3Stream = function () {
        var enabled = document.getElementById('mp3_stream_enabled').checked;
        var url = document.getElementById('mp3_stream_url').value.trim();
        var statusEl = document.getElementById('mp3_stream_status');

        if (enabled) {
            if (!url) {
                showToast('MP3 URL gerekli', 'error');
                document.getElementById('mp3_stream_enabled').checked = false;
                return;
            }
            // URL'yi localStorage'a kaydet (sayfa yenilemede korunsun)
            localStorage.setItem(MP3_URL_KEY, url);
            statusEl.textContent = 'Akış başlatılıyor...';
            statusEl.style.color = '#fbbf24';
            apiFetch('/api/mp3-stream/start', {
                method: 'POST',
                body: JSON.stringify({ url: url })
            })
                .then(function (result) {
                    if (!result) return;
                    if (result.status === 'ok') {
                        statusEl.textContent = 'Bağlantı bekleniyor... (Connect\'e tıklayın)';
                        statusEl.style.color = '#fbbf24';
                        showToast('MP3 akışı bağlantı sonrası başlayacak', 'success');
                    } else {
                        statusEl.textContent = 'Hata: ' + result.message;
                        statusEl.style.color = '#f87171';
                        document.getElementById('mp3_stream_enabled').checked = false;
                        showToast(result.message, 'error');
                    }
                })
                .catch(function (err) {
                    statusEl.textContent = 'Bağlantı hatası';
                    statusEl.style.color = '#f87171';
                    document.getElementById('mp3_stream_enabled').checked = false;
                    showToast('MP3 akış hatası: ' + err.message, 'error');
                });
        } else {
            // Kullanıcı toggle'ı kapattı — stop API'sini çağır
            // URL'yi localStorage'da bırak (URL korunsun, sadece mod kapansın)
            statusEl.textContent = 'Akış durduruluyor...';
            statusEl.style.color = '#fbbf24';
            apiFetch('/api/mp3-stream/stop', { method: 'POST' })
                .then(function (result) {
                    if (!result) return;
                    statusEl.textContent = 'MP3 modu kapalı';
                    statusEl.style.color = '#6a6a8a';
                    showToast('MP3 akışı durduruldu', 'success');
                })
                .catch(function (err) {
                    statusEl.textContent = '';
                    showToast('Durdurma hatası: ' + err.message, 'error');
                });
        }
    };

    function checkMp3StreamStatus() {
        // Önce localStorage'dan kayıtlı URL'yi yükle
        var savedUrl = localStorage.getItem(MP3_URL_KEY);
        if (savedUrl) {
            var urlInput = document.getElementById('mp3_stream_url');
            if (urlInput && !urlInput.value) {
                urlInput.value = savedUrl;
            }
        }

        apiFetch('/api/mp3-stream/status')
            .then(function (result) {
                if (!result) return;
                var statusEl = document.getElementById('mp3_stream_status');
                var urlInput = document.getElementById('mp3_stream_url');

                // URL'yi sunucudan veya localStorage'dan al
                var activeUrl = result.url || localStorage.getItem(MP3_URL_KEY);
                if (activeUrl && urlInput && !urlInput.value) {
                    urlInput.value = activeUrl;
                }
                // Sunucudan URL geldiyse localStorage'ı da güncelle
                if (result.url) {
                    localStorage.setItem(MP3_URL_KEY, result.url);
                }

                if (result.streaming) {
                    document.getElementById('mp3_stream_enabled').checked = true;
                    statusEl.textContent = 'Akış aktif';
                    statusEl.style.color = '#34d399';
                } else if (result.pending) {
                    document.getElementById('mp3_stream_enabled').checked = true;
                    statusEl.textContent = 'Bağlantı bekleniyor... (Connect\'e tıklayın)';
                    statusEl.style.color = '#fbbf24';
                } else {
                    // Ne streaming ne pending — toggle kapalı bırak (kullanıcı kapatmış)
                    document.getElementById('mp3_stream_enabled').checked = false;
                    if (statusEl.textContent === 'Akış aktif' ||
                        statusEl.textContent === 'Bağlantı bekleniyor... (Connect\'e tıklayın)') {
                        statusEl.textContent = '';
                    }
                }
            })
            .catch(function () { });
    }

    function checkSessionStatus() {
        apiFetch('/api/session/status')
            .then(function (result) {
                if (!result) return;
                var badge = document.getElementById('session-status-badge');
                if (!badge) return;
                var label = badge.querySelector('.status-text');
                if (result.session_busy) {
                    badge.classList.remove('status-badge--ready');
                    badge.classList.add('status-badge--busy');
                    if (label) label.textContent = 'Test Ediliyor';
                    badge.style.background = 'rgba(239,68,68,0.15)';
                    badge.style.border = '1px solid rgba(239,68,68,0.3)';
                    badge.style.color = '#f87171';
                } else {
                    badge.classList.remove('status-badge--busy');
                    badge.classList.add('status-badge--ready');
                    if (label) label.textContent = 'Hazır';
                    badge.style.background = '';
                    badge.style.border = '';
                    badge.style.color = '';
                }
            })
            .catch(function () { });
    }

    // ============================================================
    // Init: load config on page load
    // ============================================================
    loadConfig();
    checkMp3StreamStatus();
    checkSessionStatus();
    setInterval(checkSessionStatus, 5000);
    // Expose toggle function to global scope for HTML onchange
    window.toggleVoiceIdInput = function () {
        var gender = document.getElementById('tts_voice_gender').value;
        var container = document.getElementById('tts_voice_id_container');
        if (container) {
            if (gender === 'custom') {
                container.classList.remove('hidden');
            } else {
                container.classList.add('hidden');
            }
        }
    };


    window.handleVocabFileUpload = function (targetId, inputElem) {
        if (!inputElem.files || inputElem.files.length === 0) return;
        var file = inputElem.files[0];
        if (file.size > 5 * 1024 * 1024) { // Max 5MB
            showToast('Dosya çok büyük (Max 5MB)', 'error');
            return;
        }
        var reader = new FileReader();
        reader.onload = function (e) {
            var content = e.target.result;

            if (file.name.toLowerCase().endsWith('.json')) {
                try {
                    var obj = JSON.parse(content);
                    var lines = [];
                    if (Array.isArray(obj)) {
                        obj.forEach(function (item) {
                            if (typeof item === 'string') {
                                lines.push(item);
                            } else if (item && (item.word || item.content)) {
                                var w = item.word || item.content;
                                var p = item.pronunciations || item.sounds_like || item.soundsLike;
                                if (p && Array.isArray(p) && p.length > 0) {
                                    lines.push(w + ' | ' + p.join(', '));
                                } else if (p && typeof p === 'string') {
                                    lines.push(w + ' | ' + p);
                                } else {
                                    lines.push(w);
                                }
                            }
                        });
                    } else if (typeof obj === 'object') {
                        Object.keys(obj).forEach(function (key) {
                            var p = obj[key];
                            if (p && Array.isArray(p) && p.length > 0) {
                                lines.push(key + ' | ' + p.join(', '));
                            } else if (p && typeof p === 'string') {
                                lines.push(key + ' | ' + p);
                            } else {
                                lines.push(key);
                            }
                        });
                    }
                    content = lines.join('\n');
                } catch (err) {
                    showToast('Hatalı JSON formatı', 'error');
                    inputElem.value = "";
                    return;
                }
            }

            var el = document.getElementById(targetId);
            if (el) {
                el.value = content;
                showToast(file.name + ' yüklendi. Kaydetmeyi unutmayın.', 'success');
                // Dosya yüklendikten sonra sayacı güncelle
                var counters = {
                    'stt_deepgram_vocabulary': ['vocab_count_deepgram', 100],
                    'stt_gladia_vocabulary': ['vocab_count_gladia', 250],
                    'stt_speechmatics_vocabulary': ['vocab_count_speechmatics', 1000]
                };
                if (counters[targetId]) {
                    updateVocabCount(targetId, counters[targetId][0], counters[targetId][1]);
                }
            }
        };
        reader.onerror = function () {
            showToast('Dosya okuma hatası', 'error');
        };
        reader.readAsText(file, "UTF-8");
        // Aynı dosyayı tekrar seçebilmek için input'u sıfırla
        inputElem.value = "";
    };
})();
