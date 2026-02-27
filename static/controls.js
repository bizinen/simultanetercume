
(function () {
    'use strict';

    // Prevent double initialization
    if (window.__controlsLoaded) return;
    window.__controlsLoaded = true;

    // Inject styles immediately
    injectStyles();
    // Inject header button
    injectHeaderButton();

    // Try to find and inject into conversation panel
    function init() {
        // Look for conversation container with multiple strategies
        var container = findConversationContainer();

        if (container) {
            createControlPanel(container);
        } else {
            // Retry after short delay - Pipecat client may still be loading
            setTimeout(init, 500);
        }
    }

    function findConversationContainer() {
        // Strategy 1: Look for Pipecat's message container using data-slot
        var messageContainer = document.querySelector('[data-slot="messages"]');
        if (messageContainer) {
            return messageContainer.parentElement || messageContainer;
        }

        // Strategy 2: Look for transcript container
        var transcript = document.querySelector('[data-slot="transcript"]');
        if (transcript) {
            return transcript.parentElement || transcript;
        }

        // Strategy 3: Look for conversation tab panel content
        var conversationPanel = document.querySelector('[role="tabpanel"]');
        if (conversationPanel) {
            return conversationPanel;
        }

        // Strategy 4: Find by common layout patterns - main content area
        var mainContent = document.querySelector('main') ||
            document.querySelector('[class*="content"]') ||
            document.querySelector('[class*="chat"]') ||
            document.querySelector('[class*="message"]');
        if (mainContent) {
            return mainContent;
        }

        // Strategy 5: Look for the area above the input field
        var inputField = document.querySelector('input[placeholder*="Connect"]') ||
            document.querySelector('input[placeholder*="send"]') ||
            document.querySelector('textarea');
        if (inputField) {
            var parent = inputField.parentElement;
            while (parent && parent !== document.body) {
                if (parent.previousElementSibling) {
                    return parent.previousElementSibling;
                }
                parent = parent.parentElement;
            }
        }

        return null;
    }

    function createControlPanel(container) {
        // Remove existing panel if any
        var existing = document.getElementById('translation-controls');
        if (existing) existing.remove();

        var panel = document.createElement('div');
        panel.id = 'translation-controls';
        panel.innerHTML = `
            <div class="controls-row">
                <div class="control-group speed-group">
                    <span class="control-label">Konuşma hızı</span>
                    <div class="speed-buttons">
                        <button data-speed="0.8" id="speed-080">0.8x</button>
                        <button data-speed="0.85" id="speed-085">0.85x</button>
                        <button data-speed="0.9" id="speed-090">0.9x</button>
                        <button data-speed="0.95" id="speed-095">0.95x</button>
                        <button data-speed="1.0" id="speed-100" class="active">1x</button>
                        <button data-speed="1.05" id="speed-105">1.05x</button>
                        <button data-speed="1.1" id="speed-110">1.1x</button>
                    </div>
                </div>
                <div class="control-group">
                    <span class="control-label">Gürültü filtresi</span>
                    <button id="noise-toggle" class="toggle-btn active">Aktif</button>
                </div>
                <div class="control-group actions-group">
                    <button class="action-btn" id="clear-buffer">Temizle</button>
                    <button class="action-btn action-danger" id="reset-all">Sıfırla</button>
                </div>
                <div class="control-group actions-group download-group">
                    <button class="action-btn download-btn" id="download-audio" style="display:none" title="Download audio log (original + filtered)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; margin-right: 4px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Audio Log
                    </button>
                    <button class="action-btn download-btn" id="download-jsonl" title="Download chunk report (JSONL)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; margin-right: 4px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Chunk Report
                    </button>
                </div>
            </div>
            <div id="translation-list-container">
                <div class="list-header">
                    <span>Çeviriler</span>
                    <span id="translation-count" class="count-badge">0</span>
                </div>
                <div id="translation-list"></div>
            </div>
            <div class="status-bar" id="control-status">Bağlantı kontrol ediliyor...</div>
        `;

        // Clear container completely and add only our panel
        container.innerHTML = '';
        container.appendChild(panel);

        // Attach event handlers
        attachEventHandlers(panel);

        // Initialize connections
        checkServerConnection();
        findDataChannel();
    }

    function attachEventHandlers(panel) {
        // Speed buttons
        var speedButtons = panel.querySelectorAll('.speed-buttons button');
        speedButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var speed = parseFloat(btn.dataset.speed);
                sendControlMessage('set_speed', { speed: speed });
                speedButtons.forEach(function (b) { b.classList.remove('active'); });
                btn.classList.add('active');
                updateStatus('Hız: ' + speed + 'x');
            });
        });

        // Noise toggle
        var noiseEnabled = true;
        var noiseBtn = panel.querySelector('#noise-toggle');
        noiseBtn.addEventListener('click', function () {
            if (noiseBtn.classList.contains('disabled-filter')) {
                updateStatus('Gürültü filtresi mevcut değil');
                return;
            }
            noiseEnabled = !noiseEnabled;
            noiseBtn.textContent = noiseEnabled ? 'Aktif' : 'Kapalı';
            noiseBtn.classList.toggle('active', noiseEnabled);
            sendControlMessage('set_noise_filter', { enabled: noiseEnabled });
            updateStatus(noiseEnabled ? 'Gürültü filtresi açıldı' : 'Gürültü filtresi kapatıldı');
        });

        // Clear buffer
        panel.querySelector('#clear-buffer').addEventListener('click', function () {
            sendControlMessage('clear_buffer', {});
            updateStatus('Buffer temizlendi');
        });

        // Reset all
        panel.querySelector('#reset-all').addEventListener('click', function () {
            if (confirm('Tüm geçmişi sıfırlamak istediğinize emin misiniz?')) {
                sendControlMessage('reset_all', {});
                updateStatus('Sıfırlandı');
            }
        });

        // Download audio log
        var downloadAudioBtn = panel.querySelector('#download-audio');
        if (downloadAudioBtn) {
            downloadAudioBtn.addEventListener('click', function () {
                updateStatus('Audio log indiriliyor...');
                window.location.href = '/api/download/audio';
            });
        }

        // Download JSONL chunk report
        var downloadJsonlBtn = panel.querySelector('#download-jsonl');
        if (downloadJsonlBtn) {
            downloadJsonlBtn.addEventListener('click', function () {
                updateStatus('Chunk report indiriliyor...');
                window.location.href = '/api/download/jsonl';
            });
        }

        // Check DEBUG_AUDIO status and show/hide audio download button
        checkDebugAudioStatus();

        // Translation list: event delegation for delete buttons
        panel.querySelector('#translation-list').addEventListener('click', function (e) {
            var btn = e.target.closest('.delete-btn');
            if (btn && !btn.disabled) {
                var id = btn.dataset.id;
                deleteTranslation(id);
            }
        });
    }

    function injectHeaderButton() {
        // Look for the header actions area
        // Strategy: Find the "Connect" button and append next to it
        var findHeaderInterval = setInterval(function () {
            var connectBtn = Array.from(document.querySelectorAll('button')).find(function (b) {
                return b.textContent.includes('Connect') || b.textContent.includes('Disconnect');
            });

            if (connectBtn) {
                if (document.getElementById('header-admin-btn')) {
                    clearInterval(findHeaderInterval);
                    return;
                }

                var container = connectBtn.parentElement;
                if (container) {
                    var btn = document.createElement('button');
                    btn.id = 'header-admin-btn';
                    btn.textContent = 'Settings';
                    // Copy classes from the Connect button to match dimensions/style exactly
                    btn.className = connectBtn.className;
                    btn.classList.add('header-admin-btn');
                    btn.classList.add('btn');

                    btn.onclick = function () {
                        window.open('/admin', '_blank');
                    };

                    // Insert before the connect button
                    container.insertBefore(btn, connectBtn);
                    clearInterval(findHeaderInterval);
                }
            }
        }, 1000);

        // Stop looking after 30 seconds
        setTimeout(function () { clearInterval(findHeaderInterval); }, 30000);
    }

    function injectStyles() {
        if (document.getElementById('pipecat-controls-styles')) return;

        var style = document.createElement('style');
        style.id = 'pipecat-controls-styles';
        style.textContent = `
        
            #translation-controls {
                background: var(--color-background, #fff);
                color: var(--color-foreground, #111);
                font-family: var(--font-sans, "Geist", "Inter", -apple-system, "Segoe UI", Roboto, sans-serif);
                font-size: var(--text-sm, 0.875rem);
                padding: var(--spacing, 0.25rem) 1.25rem 1.25rem;
                margin: 0;
                width: 100%;
                height: 100%;
                box-sizing: border-box;
                display: flex;
                flex-direction: column;
                border: none;
            }

            /* Header button styles */
            .header-admin-btn {
                background-color: orange !important; /* Force red background */
                border-color: orange !important;     /* Force red border */
                color: white !important;
                margin-right: 0.75rem !important;
                cursor: pointer;
                /* Allow other styles (padding, font, rounded) to inherit from copied classes */
            }
            .header-admin-btn:hover {
                background-color: orange !important;
                border-color: orange !important;
            }

            #translation-controls .controls-row {
                display: flex;
                flex-wrap: wrap;
                gap: 1rem;
                align-items: flex-end;
                flex-shrink: 0;
                padding-bottom: 0.75rem;
                border-bottom: 1px solid var(--color-border, #e5e5e5);
            }

            #translation-controls .control-group {
                display: flex;
                flex-direction: column;
                gap: 0.25rem;
            }

            #translation-controls .speed-group { flex: 1; min-width: 12rem; }
            #translation-controls .actions-group { flex-direction: row; gap: 0.5rem; }

            #translation-controls .control-label {
                font-size: var(--text-xs, 0.75rem);
                color: var(--color-muted-foreground, #71717a);
                letter-spacing: 0.02em;
            }

            #translation-controls .speed-buttons {
                display: flex;
                gap: 0.25rem;
            }

            #translation-controls .speed-buttons button {
                background: var(--color-secondary, #f4f4f5);
                border: 1px solid var(--color-border, #e5e5e5);
                color: var(--color-secondary-foreground, #18181b);
                padding: 0.375rem 0.625rem;
                border-radius: var(--radius-md, 0.375rem);
                cursor: pointer;
                font-size: var(--text-xs, 0.75rem);
                font-family: inherit;
                font-weight: 400;
                transition: background-color 0.15s, border-color 0.15s;
            }

            #translation-controls .toggle-btn,
            #translation-controls .action-btn {
                background: var(--color-secondary, #f4f4f5);
                border: 1px solid var(--color-border, #e5e5e5);
                color: var(--color-secondary-foreground, #18181b);
                padding: 0.375rem 0.625rem;
                border-radius: var(--radius-md, 0.375rem);
                cursor: pointer;
                font-size: var(--text-xs, 0.75rem);
                font-family: inherit;
                font-weight: 500;
                transition: background-color 0.15s, border-color 0.15s;
            }

            #translation-controls .speed-buttons button:hover,
            #translation-controls .toggle-btn:hover:not(.disabled-filter),
            #translation-controls .action-btn:hover:not(:disabled) {
                background: var(--color-accent, #e4e4e7);
                border-color: var(--color-border, #e5e5e5);
            }

            #translation-controls .speed-buttons button.active,
            #translation-controls .toggle-btn.active {
                background: var(--color-active, #10b981);
                border-color: var(--color-active, #10b981);
                color: var(--color-active-foreground, #fff);
            }
            #translation-controls .toggle-btn.active:hover { color: #000; }

            #translation-controls .toggle-btn.disabled-filter {
                opacity: 0.5;
                cursor: not-allowed;
            }

            #translation-controls .action-btn.action-danger {
                background: var(--color-destructive, #ef4444);
                border-color: var(--color-destructive, #ef4444);
                color: #fff;
            }
            #translation-controls .action-btn.action-danger:hover { opacity: 0.9; color: #000; }

            #translation-controls .download-btn {
                background: var(--color-secondary, #f4f4f5);
                border: 1px solid var(--color-border, #e5e5e5);
                color: var(--color-secondary-foreground, #18181b);
                display: inline-flex;
                align-items: center;
            }
            #translation-controls .download-btn:hover {
                background: var(--color-accent, #e4e4e7);
            }

            #translation-list-container {
                margin-top: 0.75rem;
                padding-top: 0.75rem;
                border-top: 1px solid var(--color-border, #e5e5e5);
                flex: 1;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }

            #translation-list-container .list-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-size: var(--text-xs, 0.75rem);
                color: var(--color-muted-foreground, #71717a);
                margin-bottom: 0.5rem;
                flex-shrink: 0;
            }

            #translation-list-container .count-badge {
                background: var(--color-muted, #f4f4f5);
                color: var(--color-muted-foreground, #71717a);
                padding: 0.125rem 0.5rem;
                border-radius: var(--radius-sm, 0.25rem);
                font-size: 0.7rem;
            }

            #translation-list {
                flex: 1;
                overflow-y: auto;
                display: flex;
                flex-direction: column;
                gap: 0.25rem;
            }

            #translation-list::-webkit-scrollbar { width: 6px; }
            #translation-list::-webkit-scrollbar-track { background: transparent; }
            #translation-list::-webkit-scrollbar-thumb {
                background: var(--color-border, #e5e5e5);
                border-radius: 3px;
            }

            .translation-row {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.5rem 0.625rem;
                border-radius: var(--radius-md, 0.375rem);
                background: var(--color-muted, #f4f4f5);
                font-size: var(--text-xs, 0.75rem);
                border-left: 3px solid var(--color-border, #e5e5e5);
            }

            .translation-row.status-speaking {
                border-left-color: var(--color-active, #10b981);
                background: var(--color-active-accent, rgba(16, 185, 129, 0.1));
            }
            .translation-row.status-queued { border-left-color: var(--color-warning, #eab308); }
            .translation-row.status-translating { border-left-color: var(--color-client, #3b82f6); }
            .translation-row.status-pending { border-left-color: var(--color-muted-foreground, #71717a); }
            .translation-row.status-done { opacity: 0.7; border-left-color: var(--color-border); }
            .translation-row.status-cancelled { opacity: 0.5; text-decoration: line-through; }

            .translation-row .text-content { flex: 1; overflow: hidden; min-width: 0; }

            .translation-row .source {
                color: var(--color-foreground, #111);
                font-weight: 500;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            .translation-row .translated {
                color: var(--color-muted-foreground, #71717a);
                font-size: 0.7rem;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            .translation-row .status-badge {
                font-size: 0.65rem;
                padding: 0.125rem 0.375rem;
                border-radius: var(--radius-xs, 2px);
                background: var(--color-border, #e5e5e5);
                color: var(--color-muted-foreground, #71717a);
                text-transform: uppercase;
                min-width: 3rem;
                text-align: center;
                flex-shrink: 0;
            }

            .translation-row .delete-btn {
                background: transparent;
                border: 1px solid var(--color-destructive, #ef4444);
                color: var(--color-destructive, #ef4444);
                padding: 0.2rem 0.5rem;
                border-radius: var(--radius-sm, 0.25rem);
                cursor: pointer;
                font-size: 0.65rem;
                flex-shrink: 0;
            }
            .translation-row .delete-btn:hover:not(:disabled) { opacity: 0.9; }
            .translation-row .delete-btn:disabled { opacity: 0.4; cursor: not-allowed; }

            #translation-controls .status-bar {
                font-size: var(--text-xs, 0.75rem);
                color: var(--color-muted-foreground, #71717a);
                margin-top: 0.5rem;
                padding-top: 0.5rem;
                border-top: 1px solid var(--color-border, #e5e5e5);
            }


        `;
        document.head.appendChild(style);
    }

    // Global state
    var dataChannel = null;
    var serverConnected = false;
    var pollingInterval = null;

    function checkServerConnection() {
        sendControlMessage('get_status', {}, function (response) {
            if (response && response.status === 'ok') {
                serverConnected = true;
                updateConnectionBadge(true);
                updateStatus('Bağlandı');

                // Update noise filter button based on server state
                var noiseBtn = document.querySelector('#noise-toggle');
                if (noiseBtn && response.noise_filter_enabled === false) {
                    noiseBtn.textContent = 'Kapalı';
                    noiseBtn.classList.remove('active');
                }

                // Render initial translations if available
                if (response.translations) {
                    renderTranslationList(response.translations);
                }

                // Start polling for translation list updates
                startPolling();
            } else {
                setTimeout(checkServerConnection, 2000);
            }
        });
    }

    function updateConnectionBadge(connected) {
        var badge = document.getElementById('connection-badge');
        if (!badge) return;
        badge.classList.toggle('connected', connected);
    }

    function startPolling() {
        if (pollingInterval) return;
        pollingInterval = setInterval(function () {
            sendControlMessage('get_translations', {}, function (response) {
                if (response && response.translations) {
                    renderTranslationList(response.translations);
                }
            });
        }, 1500);
    }

    function renderTranslationList(translations) {
        var listEl = document.getElementById('translation-list');
        var countEl = document.getElementById('translation-count');
        if (!listEl) return;

        countEl.textContent = translations.length;

        var statusLabels = {
            pending: 'Bekliyor',
            translating: 'Çevriliyor',
            queued: 'Sırada',
            speaking: 'Konuşuyor',
            done: 'Bitti',
            cancelled: 'İptal'
        };

        var html = translations.map(function (t) {
            var statusLabel = statusLabels[t.status] || t.status;
            var isDeletable = ['pending', 'translating', 'queued', 'speaking'].includes(t.status);

            return '<div class="translation-row status-' + t.status + '">' +
                '<span class="status-badge">' + escapeHtml(statusLabel) + '</span>' +
                '<div class="text-content">' +
                '<div class="source" title="' + escapeHtml(t.source_text) + '">' + escapeHtml(t.source_text) + '</div>' +
                '<div class="translated" title="' + escapeHtml(t.translated_text) + '">' + escapeHtml(t.translated_text) + '</div>' +
                '</div>' +
                '<button class="delete-btn" data-id="' + t.id + '"' +
                (isDeletable ? '' : ' disabled') +
                '>Sil</button>' +
                '</div>';
        }).join('');

        if (listEl.innerHTML !== html) {
            var wasScrolledToBottom = listEl.scrollTop + listEl.clientHeight >= listEl.scrollHeight - 10;
            listEl.innerHTML = html;
            if (wasScrolledToBottom) {
                listEl.scrollTop = listEl.scrollHeight;
            }
        }
    }

    function deleteTranslation(id) {
        sendControlMessage('delete_translation', { id: id }, function (response) {
            if (response && response.status === 'ok') {
                updateStatus('Çeviri silindi');
                if (response.translations) {
                    renderTranslationList(response.translations);
                }
            } else {
                updateStatus('Silme başarısız: ' + (response && response.message || 'Bilinmeyen hata'));
            }
        });
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function findDataChannel() {
        if (!window.__pcIntercepted) {
            window.__pcIntercepted = true;
            var originalPC = window.RTCPeerConnection;
            window.RTCPeerConnection = function () {
                var pc = new (Function.prototype.bind.apply(originalPC, [null].concat(Array.prototype.slice.call(arguments))))();
                window.__lastPC = pc;

                pc.addEventListener('datachannel', function (event) {
                    setupDataChannel(event.channel);
                });

                return pc;
            };
            window.RTCPeerConnection.prototype = originalPC.prototype;
        }

        var checkInterval = setInterval(function () {
            if (dataChannel && dataChannel.readyState === 'open') {
                clearInterval(checkInterval);
                updateStatus('Bağlandı (WebRTC)');
            }
        }, 1000);

        setTimeout(function () { clearInterval(checkInterval); }, 15000);
    }

    function setupDataChannel(channel) {
        if (channel.readyState === 'open') {
            dataChannel = channel;
            updateStatus('Bağlandı (WebRTC)');
        } else {
            channel.addEventListener('open', function () {
                dataChannel = channel;
                updateStatus('Bağlandı (WebRTC)');
            });
        }
    }

    var httpOnlyTypes = ['get_translations', 'get_status', 'delete_translation', 'delete_last'];

    function sendControlMessage(type, data, callback) {
        if (dataChannel && dataChannel.readyState === 'open' && httpOnlyTypes.indexOf(type) === -1) {
            try {
                dataChannel.send(JSON.stringify({ type: type, data: data }));
                if (callback) callback({ status: 'ok' });
                return;
            } catch (e) {
                // Data channel send failed, fall through to HTTP
            }
        }

        fetch('/api/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: type, data: data })
        }).then(function (r) {
            if (r.ok) {
                return r.json();
            }
            throw new Error('API request failed: ' + r.status);
        }).then(function (response) {
            if (callback) callback(response);

            if (type === 'get_status' && response.noise_filter_enabled !== undefined) {
                var noiseBtn = document.querySelector('#noise-toggle');
                if (noiseBtn && !response.noise_filter_enabled) {
                    noiseBtn.textContent = 'Kapalı';
                    noiseBtn.classList.remove('active');
                }
            }
        }).catch(function () {
            updateStatus('Sunucuya ulaşılamadı');
            if (callback) callback(null);
        });
    }

    function checkDebugAudioStatus() {
        fetch('/api/debug/status')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.debug_audio) {
                    var audioBtn = document.querySelector('#download-audio');
                    if (audioBtn) {
                        audioBtn.style.display = 'inline-flex';
                    }
                }
            })
            .catch(function () {
                // Silently ignore — audio button stays hidden
            });
    }

    function updateStatus(msg) {
        var status = document.querySelector('#control-status');
        if (status) {
            status.textContent = msg;
            if (msg.indexOf('Bağlandı') === -1 && msg.indexOf('kontrol') === -1) {
                setTimeout(function () {
                    if (dataChannel && dataChannel.readyState === 'open') {
                        status.textContent = 'Bağlandı (WebRTC)';
                    } else if (serverConnected) {
                        status.textContent = 'Bağlandı (HTTP)';
                    } else {
                        status.textContent = 'Hazır';
                    }
                }, 3000);
            }
        }
    }

    // Cleanup on page unload
    window.addEventListener('beforeunload', function () {
        if (pollingInterval) clearInterval(pollingInterval);
    });

    // Initialize
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();