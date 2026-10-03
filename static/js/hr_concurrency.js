/**
 * HR Multi-User Concurrency & Real-Time Action Isolation Controller
 * Provides sub-3-second real-time synchronization across all HR users:
 *   - Isolated notifications tracking
 *   - Mutual exclusion locks for Interview Scheduling, Rescheduling & Final Decisions
 *   - Candidate evaluation locking & automatic evaluation form hiding for non-evaluators
 */
(function() {
    'use strict';

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.content) return meta.content;
        const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input && input.value) return input.value;
        return getCookie('csrftoken') || '';
    }

    const currentLocks = new Map(); // key: targetModel:targetId:actionType -> intervalId
    let lastSyncData = null;
    let syncIntervalId = null;

    function showConcurrencyAlert(message) {
        let container = document.getElementById('hr-concurrency-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'hr-concurrency-toast-container';
            container.style.cssText = 'position: fixed; top: 24px; right: 24px; z-index: 99999; display: flex; flex-direction: column; gap: 10px; max-width: 400px; pointer-events: none;';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = 'hr-concurrency-toast';
        toast.style.cssText = 'background: #ffffff; border-left: 4px solid #f59e0b; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.15), 0 8px 10px -6px rgba(0,0,0,0.1); border-radius: 8px; padding: 14px 16px; display: flex; align-items: flex-start; gap: 12px; pointer-events: auto; animation: slideInRight 0.3s ease; border-top: 1px solid #f1f5f9; border-right: 1px solid #f1f5f9; border-bottom: 1px solid #f1f5f9;';

        toast.innerHTML = `
            <div style="width: 24px; height: 24px; border-radius: 50%; background: #fef3c7; color: #d97706; display: flex; align-items: center; justify-content: center; font-size: 12px; flex-shrink: 0; margin-top: 1px;">
                <i class="fas fa-lock"></i>
            </div>
            <div style="flex: 1;">
                <h5 style="margin: 0 0 3px 0; font-size: 13.5px; font-weight: 700; color: #1e293b;">Action In Progress</h5>
                <p style="margin: 0; font-size: 12.5px; color: #64748b; line-height: 1.4;">${message}</p>
            </div>
            <button type="button" style="background: transparent; border: none; color: #94a3b8; font-size: 14px; cursor: pointer; padding: 0 4px;" onclick="this.parentElement.remove()">
                &times;
            </button>
        `;

        container.appendChild(toast);
        setTimeout(() => {
            if (toast.parentElement) {
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.3s ease';
                setTimeout(() => toast.remove(), 300);
            }
        }, 6000);
    }

    async function acquireLock(targetId, actionType, targetModel = 'Application') {
        const csrfToken = getCSRFToken();
        const lockKey = `${targetModel}:${targetId}:${actionType}`;

        try {
            const resp = await fetch('/hr/api/lock/acquire/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    target_model: targetModel,
                    target_id: targetId,
                    action_type: actionType
                })
            });

            if (!resp.ok) {
                return { success: false, message: 'Server returned error checking lock.' };
            }

            const data = await resp.json();
            if (data.success) {
                // Heartbeat every 25 seconds
                if (currentLocks.has(lockKey)) {
                    clearInterval(currentLocks.get(lockKey));
                }
                const heartbeatId = setInterval(() => {
                    fetch('/hr/api/lock/heartbeat/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCSRFToken(),
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify({
                            target_model: targetModel,
                            target_id: targetId,
                            action_type: actionType
                        })
                    }).catch(() => {});
                }, 25000);

                currentLocks.set(lockKey, heartbeatId);
                // Trigger immediate sync tick
                triggerSyncSoon(100);
                return { success: true };
            } else {
                return {
                    success: false,
                    locked: true,
                    locked_by: data.locked_by || 'another HR user',
                    message: data.message || `Currently being handled by ${data.locked_by}.`
                };
            }
        } catch (e) {
            console.error('Error acquiring action lock:', e);
            return { success: false, message: 'Connection error while acquiring lock.' };
        }
    }

    async function acquireBatchLock(targetIds, actionType, targetModel = 'Application') {
        const csrfToken = getCSRFToken();
        try {
            const resp = await fetch('/hr/api/lock/acquire/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    target_model: targetModel,
                    target_ids: targetIds,
                    action_type: actionType
                })
            });

            if (!resp.ok) return { success: false, message: 'Server returned error checking lock.' };

            const data = await resp.json();
            if (data.success) {
                targetIds.forEach(id => {
                    const lockKey = `${targetModel}:${id}:${actionType}`;
                    currentLocks.set(lockKey, true);
                });
                triggerSyncSoon(100);
                return { success: true };
            } else {
                return {
                    success: false,
                    locked: true,
                    locked_by: data.locked_by || 'another HR user',
                    message: data.message || `Candidates are currently being handled by ${data.locked_by}.`
                };
            }
        } catch (e) {
            console.error('Error acquiring batch action lock:', e);
            return { success: false, message: 'Connection error while acquiring batch lock.' };
        }
    }

    async function releaseLock(targetId, actionType, targetModel = 'Application') {
        const csrfToken = getCSRFToken();
        const lockKey = `${targetModel}:${targetId}:${actionType}`;

        if (currentLocks.has(lockKey)) {
            const intId = currentLocks.get(lockKey);
            if (typeof intId === 'number') clearInterval(intId);
            currentLocks.delete(lockKey);
        }

        try {
            await fetch('/hr/api/lock/release/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    target_model: targetModel,
                    target_id: targetId,
                    action_type: actionType
                })
            });
            triggerSyncSoon(100);
        } catch (e) {
            console.error('Error releasing action lock:', e);
        }
    }

    async function releaseBatchLock(targetIds, actionType, targetModel = 'Application') {
        const csrfToken = getCSRFToken();
        targetIds.forEach(id => {
            const lockKey = `${targetModel}:${id}:${actionType}`;
            if (currentLocks.has(lockKey)) {
                const intId = currentLocks.get(lockKey);
                if (typeof intId === 'number') clearInterval(intId);
                currentLocks.delete(lockKey);
            }
        });

        try {
            await fetch('/hr/api/lock/release/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    target_model: targetModel,
                    target_ids: targetIds,
                    action_type: actionType
                })
            });
            triggerSyncSoon(100);
        } catch (e) {
            console.error('Error releasing batch action lock:', e);
        }
    }

    // Auto-release all locks on page unload
    window.addEventListener('beforeunload', function() {
        for (const [key, intervalId] of currentLocks.entries()) {
            if (typeof intervalId === 'number') clearInterval(intervalId);
            const [targetModel, targetId, actionType] = key.split(':');
            navigator.sendBeacon(
                '/hr/api/lock/release/',
                new Blob([JSON.stringify({ target_model: targetModel, target_id: targetId, action_type: actionType })], { type: 'application/json' })
            );
        }
    });

    // =========================================================================
    // REAL-TIME SYNCHRONIZATION ENGINE (Sub-3-second live sync)
    // =========================================================================
    async function executeLiveSync() {
        try {
            const resp = await fetch('/hr/api/live-sync/', {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!resp.ok) return;
            const data = await resp.json();
            if (data.status !== 'success') return;
            lastSyncData = data;
            applyRealtimeSync(data);
        } catch (err) {
            // Silently retry on next tick
        }
    }

    function applyRealtimeSync(data) {
        const currentUserId = data.current_user_id;

        // 1. Sync Notifications UI
        const bell = document.getElementById('notif-bell-btn');
        const badge = document.getElementById('notif-badge');
        const pill = document.getElementById('notif-unread-pill');

        if (data.unread_count > 0) {
            if (bell) bell.classList.add('has-unread');
            if (badge) {
                badge.textContent = data.unread_count;
                badge.style.display = 'inline-flex';
            }
            if (pill) pill.textContent = data.unread_count + ' unread';
        } else {
            if (bell) bell.classList.remove('has-unread');
            if (badge) badge.style.display = 'none';
            if (pill) pill.textContent = 'All caught up';
        }

        if (window.renderNotificationsList && data.notifications) {
            window.renderNotificationsList(data.notifications);
        }

        // 2. Map of active locks held by OTHER users: candId -> lockObj
        const locksMap = new Map();
        if (data.active_locks && Array.isArray(data.active_locks)) {
            data.active_locks.forEach(lock => {
                if (lock.user_id !== currentUserId) {
                    const idStr = String(lock.target_id);
                    locksMap.set(`${idStr}:${lock.action_type}`, lock);
                    locksMap.set(`${lock.target_model}:${idStr}:${lock.action_type}`, lock);
                    // General lookup by target_id (prioritize RESCHEDULE and SCHEDULE locks)
                    const existing = locksMap.get(idStr);
                    if (!existing || ['RESCHEDULE', 'SCHEDULE'].includes(lock.action_type)) {
                        locksMap.set(idStr, lock);
                    }
                }
            });
        }

        // 3. Map of ongoing evaluations: appId -> evalObj
        const ongoingEvalsMap = new Map();
        if (data.ongoing_evaluations && Array.isArray(data.ongoing_evaluations)) {
            data.ongoing_evaluations.forEach(ev => {
                ongoingEvalsMap.set(String(ev.application_id), ev);
            });
        }

        // 4. Update Action Buttons across pages (Schedule, Reschedule, Final Review)
        document.querySelectorAll('button[data-action-btn], a[data-action-btn]').forEach(el => {
            const candId = el.getAttribute('data-cand-id');
            const actionType = el.getAttribute('data-action-btn');
            if (!candId) return;

            // Remember original state ONLY if element is NOT currently disabled/locked
            const isCurrentlyDisabled = el.disabled || el.classList.contains('disabled');
            const currentHtml = el.innerHTML;
            const hasLockText = currentHtml.indexOf('fa-lock') !== -1 || currentHtml.indexOf('In Evaluation') !== -1 || currentHtml.indexOf('Locked') !== -1;
            if (!isCurrentlyDisabled && !hasLockText) {
                if (!el.hasAttribute('data-orig-html')) {
                    el.setAttribute('data-orig-html', currentHtml);
                }
                if (!el.hasAttribute('data-orig-style')) {
                    el.setAttribute('data-orig-style', el.getAttribute('style') || '');
                }
                if (!el.hasAttribute('data-orig-onclick')) {
                    el.setAttribute('data-orig-onclick', el.getAttribute('onclick') || '');
                }
            }

            const ongoingEval = ongoingEvalsMap.get(String(candId));
            const specificLock = locksMap.get(`${candId}:${actionType}`) || (actionType !== 'EVALUATE' ? locksMap.get(String(candId)) : null);

            // 1. MANAGE / RESCHEDULE ACTION BUTTON
            if (actionType === 'RESCHEDULE') {
                if (ongoingEval) {
                    // Candidate is actively being evaluated -> Manage button must be LOCKED for EVERYONE!
                    el.disabled = true;
                    el.classList.add('disabled');
                    el.style.cssText = 'background: #f1f5f9; color: #64748b !important; border-color: #cbd5e1; cursor: not-allowed; opacity: 0.85; padding: 6px 14px; border-radius: 8px; font-weight: 700; font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px;';
                    el.innerHTML = '<i class="fas fa-lock"></i> <span>Locked</span>';
                    el.title = `Interview cannot be managed while candidate evaluation is ongoing (by ${ongoingEval.evaluator_name}).`;
                    el.onclick = function(e) { e.preventDefault(); e.stopPropagation(); };
                    return;
                } else if (specificLock) {
                    // Button is locked by another user!
                    el.disabled = true;
                    el.classList.add('disabled');
                    el.style.cssText = 'background: #f1f5f9; color: #64748b !important; border-color: #cbd5e1; cursor: not-allowed; opacity: 0.85; padding: 6px 14px; border-radius: 8px; font-weight: 700; font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px;';
                    el.innerHTML = `<i class="fas fa-lock"></i> <span>Locked (${specificLock.user_name})</span>`;
                    el.title = `Currently being handled by ${specificLock.user_name}.`;
                    el.onclick = function(e) { e.preventDefault(); e.stopPropagation(); };
                    return;
                } else {
                    // Button is free
                    if (el.disabled || el.classList.contains('disabled')) {
                        el.disabled = false;
                        el.classList.remove('disabled');
                        let origHtml = el.getAttribute('data-orig-html');
                        if (!origHtml || origHtml.indexOf('fa-lock') !== -1 || origHtml.indexOf('Locked') !== -1) {
                            origHtml = '<i class="fas fa-sliders"></i> <span>Manage</span>';
                        }
                        el.innerHTML = origHtml;
                        let origStyle = el.getAttribute('data-orig-style');
                        if (!origStyle || origStyle.indexOf('not-allowed') !== -1) {
                            origStyle = 'background: #ffffff; color: #334155 !important; border-color: #cbd5e1; cursor: pointer;';
                        }
                        el.style.cssText = origStyle;
                        const origClick = el.getAttribute('data-orig-onclick');
                        if (origClick && origClick.indexOf('hrOpenManageInterviewModal') !== -1) {
                            el.setAttribute('onclick', origClick);
                        } else if (el.hasAttribute('data-cand-id')) {
                            const cId = el.getAttribute('data-cand-id');
                            const cName = el.getAttribute('data-cand-name') || '';
                            const jTitle = el.getAttribute('data-job-title') || '';
                            const iDate = el.getAttribute('data-intv-date') || '';
                            const iTime = el.getAttribute('data-intv-time') || '';
                            const iInterviewer = el.getAttribute('data-intv-interviewer') || '';
                            const iLoc = el.getAttribute('data-intv-location') || '';
                            el.onclick = function() {
                                if (typeof window.hrOpenManageInterviewModal === 'function') {
                                    window.hrOpenManageInterviewModal(cId, cName, jTitle, iDate, iTime, iInterviewer, iLoc);
                                }
                            };
                        }
                        el.title = 'Manage Interview (Reschedule or Cancel)';
                    }
                    return;
                }
            }

            // 2. EVALUATE ACTION BUTTON
            if (actionType === 'EVALUATE') {
                const idStr = String(candId);
                const rescheduleLock = locksMap.get(`${idStr}:RESCHEDULE`)
                                    || locksMap.get(`${idStr}:SCHEDULE`)
                                    || locksMap.get(`Application:${idStr}:RESCHEDULE`)
                                    || locksMap.get(`Application:${idStr}:SCHEDULE`)
                                    || (locksMap.get(idStr) && ['RESCHEDULE', 'SCHEDULE'].includes(locksMap.get(idStr).action_type) ? locksMap.get(idStr) : null);
                if (rescheduleLock && !rescheduleLock.is_me) {
                    // Locked because another HR user is currently managing (rescheduling or cancelling) this candidate's interview
                    el.disabled = true;
                    el.classList.add('disabled');
                    el.style.cssText = 'background: #f1f5f9; color: #64748b !important; border-color: #cbd5e1; cursor: not-allowed; opacity: 0.85; padding: 6px 14px; border-radius: 8px; font-weight: 700; font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px;';
                    el.innerHTML = `<i class="fas fa-lock"></i> <span>Locked (${rescheduleLock.user_name})</span>`;
                    el.title = `Interview is currently being managed by ${rescheduleLock.user_name}.`;
                    el.removeAttribute('href');
                    el.removeAttribute('hx-get');
                    el.onclick = function(e) { e.preventDefault(); e.stopPropagation(); return false; };
                    return;
                }

                if (ongoingEval) {
                    if (ongoingEval.evaluator_id && ongoingEval.evaluator_id !== currentUserId) {
                        // Locked by other evaluator
                        el.disabled = true;
                        el.classList.add('disabled');
                        el.style.cssText = 'background: #f1f5f9; color: #64748b !important; border-color: #cbd5e1; cursor: not-allowed; opacity: 0.85; padding: 6px 14px; border-radius: 8px; font-weight: 700; font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px;';
                        el.innerHTML = `<i class="fas fa-lock"></i> <span>In Evaluation (${ongoingEval.evaluator_name})</span>`;
                        el.removeAttribute('href');
                        el.onclick = function(e) { e.preventDefault(); e.stopPropagation(); };
                    } else {
                        // My evaluation -> Continue Evaluation
                        el.disabled = false;
                        el.classList.remove('disabled');
                        el.style.cssText = 'background: #fef3c7; color: #b45309 !important; border: 1.5px solid #fde68a; padding: 6px 14px; border-radius: 8px; font-weight: 700; font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px; cursor: pointer;';
                        el.innerHTML = '<i class="fas fa-play"></i> <span>Continue Evaluation</span>';
                        el.title = 'Continue recording candidate evaluation';
                        el.onclick = null;
                        if (el.tagName.toLowerCase() === 'a') {
                            el.setAttribute('href', `/hr/candidates/applicant/${candId}/?evaluate=true`);
                        } else if (el.tagName.toLowerCase() === 'button') {
                            el.setAttribute('hx-get', `/hr/candidates/applicant/${candId}/?modal=1&evaluate=1&scroll_to=candidate-evaluation-section`);
                            el.setAttribute('hx-target', '#candidate-profile-modal-container');
                            el.setAttribute('hx-swap', 'innerHTML');
                            if (window.htmx) {
                                window.htmx.process(el);
                            }
                        }
                    }
                } else {
                    // Normal Evaluate button
                    if (el.disabled || el.classList.contains('disabled') || el.innerHTML.indexOf('In Evaluation') !== -1 || el.innerHTML.indexOf('Continue Evaluation') !== -1 || el.innerHTML.indexOf('fa-lock') !== -1 || el.innerHTML.indexOf('Locked') !== -1) {
                        el.disabled = false;
                        el.classList.remove('disabled');
                        let origHtml = el.getAttribute('data-orig-html');
                        if (!origHtml || origHtml.indexOf('fa-lock') !== -1 || origHtml.indexOf('In Evaluation') !== -1 || origHtml.indexOf('Continue Evaluation') !== -1 || origHtml.indexOf('Locked') !== -1) {
                            origHtml = '<i class="fas fa-clipboard-check"></i> <span>Evaluate</span>';
                        }
                        el.innerHTML = origHtml;
                        let origStyle = el.getAttribute('data-orig-style');
                        if (!origStyle || origStyle.indexOf('not-allowed') !== -1) {
                            origStyle = 'background: #2d5a27; color: #ffffff !important; border-color: #2d5a27; cursor: pointer;';
                        }
                        el.style.cssText = origStyle;
                        const origClick = el.getAttribute('data-orig-onclick');
                        if (origClick) {
                            el.setAttribute('onclick', origClick);
                        } else {
                            el.onclick = null;
                        }
                        if (el.tagName.toLowerCase() === 'button') {
                            el.setAttribute('hx-get', `/hr/candidates/applicant/${candId}/evaluation/start/?modal=1`);
                            el.setAttribute('hx-target', '#candidate-profile-modal-container');
                            el.setAttribute('hx-swap', 'innerHTML');
                            if (window.htmx) {
                                window.htmx.process(el);
                            }
                        }
                        el.title = 'Start recording candidate evaluation';
                    }
                }
                return;
            }

            // 3. OTHER ACTION BUTTONS
            if (specificLock) {
                // Button is locked by another user!
                el.disabled = true;
                el.classList.add('disabled');
                el.style.cssText = 'background: #f1f5f9; color: #64748b !important; border-color: #cbd5e1; cursor: not-allowed; opacity: 0.85; padding: 6px 14px; border-radius: 8px; font-weight: 700; font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px;';
                el.innerHTML = `<i class="fas fa-lock"></i> <span>Locked (${specificLock.user_name})</span>`;
                el.title = `Currently being handled by ${specificLock.user_name}.`;
            } else {
                // Button is free
                if (el.disabled || el.classList.contains('disabled')) {
                    el.disabled = false;
                    el.classList.remove('disabled');
                    el.style.cssText = el.getAttribute('data-orig-style');
                    el.innerHTML = el.getAttribute('data-orig-html');
                    const origClick = el.getAttribute('data-orig-onclick');
                    if (origClick) el.setAttribute('onclick', origClick);
                    el.title = '';
                }
            }
        });

        // 4b. Sync evaluation table status pills (Scheduled vs Ongoing)
        document.querySelectorAll('tr.eval-cand-row').forEach(row => {
            const appId = row.getAttribute('data-app-id');
            if (!appId) return;
            const ongoingEval = ongoingEvalsMap.get(String(appId));
            const statusCell = row.querySelector('.td-status');
            if (!statusCell) return;
            const currentStatus = row.getAttribute('data-status');
            if (currentStatus === 'completed') return;

            if (ongoingEval) {
                row.setAttribute('data-status', 'ongoing');
                statusCell.innerHTML = `
                    <span class="status-pill status-ongoing" style="background: #fef3c7; color: #b45309; font-weight: 700; display: inline-flex; align-items: center; gap: 4px;">
                        <i class="fas fa-spinner fa-spin"></i> Ongoing
                    </span>
                `;
            } else if (currentStatus === 'ongoing') {
                const baseStatus = row.getAttribute('data-base-status') || 'scheduled';
                row.setAttribute('data-status', baseStatus);
                if (baseStatus === 'rescheduled') {
                    statusCell.innerHTML = `
                        <div style="display: flex; flex-direction: column; align-items: flex-start; gap: 4px;">
                            <span class="status-pill status-rescheduled" style="background: #ffedd5; color: #c2410c; font-weight: 700; display: inline-flex; align-items: center; gap: 4px; border: 1px solid #fdba74;">
                                <i class="fas fa-calendar-alt"></i> RESCHEDULED
                            </span>
                        </div>
                    `;
                } else {
                    statusCell.innerHTML = `
                        <span class="status-pill status-scheduled" style="background: #dbeafe; color: #1e40af; font-weight: 700; display: inline-flex; align-items: center; gap: 4px;">
                            <i class="fas fa-clock"></i> Scheduled
                        </span>
                    `;
                }
            }
        });

        // 5. Candidate Detail Page Live Evaluation Form Hiding & Button Locking
        const candidateDetailContainer = document.getElementById('eval-form-card');
        const candidateLockedCard = document.getElementById('eval-locked-card');
        const candidatePendingCard = document.getElementById('eval-pending-card');
        const heroEvaluateBtn = document.querySelector('.hero-actions-stack .btn-evaluate');
        const toggleEvalBtn = document.getElementById('btn-toggle-eval-form');

        const pageAppId = (candidateDetailContainer ? candidateDetailContainer.getAttribute('data-app-id') : null)
                       || document.getElementById('schedApplicantId')?.value
                       || (candidateLockedCard ? candidateLockedCard.getAttribute('data-app-id') : null)
                       || (candidatePendingCard ? candidatePendingCard.getAttribute('data-app-id') : null)
                       || (heroEvaluateBtn ? (heroEvaluateBtn.getAttribute('data-cand-id') || heroEvaluateBtn.getAttribute('data-candidate-id')) : null)
                       || (toggleEvalBtn ? (toggleEvalBtn.getAttribute('data-cand-id') || toggleEvalBtn.getAttribute('data-candidate-id')) : null);

        if (pageAppId || candidateDetailContainer || toggleEvalBtn || heroEvaluateBtn) {
            const idStr = pageAppId ? String(pageAppId) : null;
            const currentEval = idStr ? ongoingEvalsMap.get(idStr) : null;
            const manageLock = idStr ? (
                locksMap.get(`${idStr}:RESCHEDULE`)
                || locksMap.get(`${idStr}:SCHEDULE`)
                || locksMap.get(`Application:${idStr}:RESCHEDULE`)
                || locksMap.get(`Application:${idStr}:SCHEDULE`)
                || (locksMap.get(idStr) && ['RESCHEDULE', 'SCHEDULE'].includes(locksMap.get(idStr).action_type) ? locksMap.get(idStr) : null)
            ) : null;

            if (manageLock && !manageLock.is_me) {
                // Interview is being managed by another HR -> HIDE FORM & LOCK BUTTONS!
                if (candidateDetailContainer) candidateDetailContainer.style.setProperty('display', 'none', 'important');
                if (candidatePendingCard) candidatePendingCard.style.display = 'none';
                if (candidateLockedCard) {
                    candidateLockedCard.style.display = 'block';
                    const lockedDesc = candidateLockedCard.querySelector('p strong');
                    if (lockedDesc) lockedDesc.textContent = manageLock.user_name;
                    const h4 = candidateLockedCard.querySelector('h4');
                    if (h4) h4.textContent = `Interview Management In Progress (Locked by ${manageLock.user_name})`;
                }
                if (toggleEvalBtn) {
                    toggleEvalBtn.disabled = true;
                    toggleEvalBtn.classList.add('disabled');
                    toggleEvalBtn.style.cssText = 'padding: 6px 14px; font-size: 12px; font-weight: 600; background: #f1f5f9; color: #64748b !important; border: 1px solid #cbd5e1; cursor: not-allowed; border-radius: 6px; display: inline-flex; align-items: center; gap: 6px;';
                    toggleEvalBtn.innerHTML = `<i class="fas fa-lock"></i> <span id="toggle-eval-text">Locked (${manageLock.user_name})</span>`;
                    toggleEvalBtn.title = `Interview is currently being managed by ${manageLock.user_name}`;
                    toggleEvalBtn.onclick = function(e) { e.preventDefault(); e.stopPropagation(); return false; };
                }
                if (heroEvaluateBtn) {
                    heroEvaluateBtn.disabled = true;
                    heroEvaluateBtn.classList.add('disabled');
                    heroEvaluateBtn.style.cssText = 'background: #f1f5f9; color: #64748b !important; border: 1px solid #cbd5e1; cursor: not-allowed;';
                    heroEvaluateBtn.innerHTML = `<i class="fas fa-lock"></i> <span>Locked (${manageLock.user_name})</span>`;
                    heroEvaluateBtn.onclick = function(e) { e.preventDefault(); e.stopPropagation(); return false; };
                }
            } else if (currentEval && currentEval.evaluator_id && currentEval.evaluator_id !== currentUserId) {
                // Candidate is being evaluated / edited by ANOTHER evaluator -> HIDE FORM & LOCK BUTTONS!
                if (candidateDetailContainer) candidateDetailContainer.style.setProperty('display', 'none', 'important');
                if (candidatePendingCard) candidatePendingCard.style.display = 'none';
                if (candidateLockedCard) {
                    candidateLockedCard.style.display = 'block';
                    const lockedDesc = candidateLockedCard.querySelector('p strong');
                    if (lockedDesc) lockedDesc.textContent = currentEval.evaluator_name;
                    const h4 = candidateLockedCard.querySelector('h4');
                    if (h4) h4.textContent = `Candidate Evaluation In Progress (Locked)`;
                }
                if (toggleEvalBtn) {
                    toggleEvalBtn.disabled = true;
                    toggleEvalBtn.classList.add('disabled');
                    toggleEvalBtn.style.cssText = 'padding: 6px 14px; font-size: 12px; font-weight: 600; background: #f1f5f9; color: #64748b !important; border: 1px solid #cbd5e1; cursor: not-allowed; border-radius: 6px; display: inline-flex; align-items: center; gap: 6px;';
                    toggleEvalBtn.innerHTML = `<i class="fas fa-lock"></i> <span id="toggle-eval-text">Editing Locked (${currentEval.evaluator_name})</span>`;
                    toggleEvalBtn.title = `Evaluation is currently being edited by ${currentEval.evaluator_name}`;
                    toggleEvalBtn.onclick = function(e) { e.preventDefault(); e.stopPropagation(); return false; };
                }
                if (heroEvaluateBtn) {
                    heroEvaluateBtn.disabled = true;
                    heroEvaluateBtn.classList.add('disabled');
                    heroEvaluateBtn.style.cssText = 'background: #f1f5f9; color: #64748b !important; border: 1px solid #cbd5e1; cursor: not-allowed;';
                    heroEvaluateBtn.innerHTML = `<i class="fas fa-lock"></i> <span>In Evaluation (${currentEval.evaluator_name})</span>`;
                    heroEvaluateBtn.onclick = function(e) { e.preventDefault(); e.stopPropagation(); return false; };
                }
            } else if (currentEval && currentEval.evaluator_id === currentUserId) {
                // Current user is the evaluator
                if (candidateLockedCard) candidateLockedCard.style.display = 'none';
                if (toggleEvalBtn) {
                    toggleEvalBtn.disabled = false;
                    toggleEvalBtn.classList.remove('disabled');
                }
                if (heroEvaluateBtn) {
                    heroEvaluateBtn.disabled = false;
                    heroEvaluateBtn.classList.remove('disabled');
                    heroEvaluateBtn.innerHTML = '<i class="fas fa-clipboard-check"></i> <span>Continue Evaluation</span>';
                }
            } else {
                // Not actively evaluated or managed by anyone
                if (candidateLockedCard) candidateLockedCard.style.display = 'none';
                if (toggleEvalBtn && (toggleEvalBtn.disabled || toggleEvalBtn.classList.contains('disabled') || toggleEvalBtn.innerHTML.indexOf('Locked') !== -1)) {
                    toggleEvalBtn.disabled = false;
                    toggleEvalBtn.classList.remove('disabled');
                    toggleEvalBtn.style.cssText = 'padding: 6px 14px; font-size: 12px; font-weight: 600; background: #2d5a27; color: #fff; border: 1.5px solid transparent; border-radius: 6px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;';
                    toggleEvalBtn.innerHTML = '<i class="fas fa-pen-to-square"></i> <span id="toggle-eval-text">Edit Evaluation</span>';
                    toggleEvalBtn.title = 'Edit Evaluation';
                    toggleEvalBtn.setAttribute('onclick', 'toggleEvaluationForm()');
                    toggleEvalBtn.onclick = function() {
                        if (typeof window.toggleEvaluationForm === 'function') window.toggleEvaluationForm();
                    };
                }
                if (heroEvaluateBtn && (heroEvaluateBtn.disabled || heroEvaluateBtn.classList.contains('disabled') || heroEvaluateBtn.innerHTML.indexOf('Locked') !== -1)) {
                    heroEvaluateBtn.disabled = false;
                    heroEvaluateBtn.classList.remove('disabled');
                    heroEvaluateBtn.style.cssText = '';
                    heroEvaluateBtn.innerHTML = '<i class="fas fa-clipboard-check"></i> <span>Evaluate Candidate</span>';
                    heroEvaluateBtn.onclick = function() {
                        if (typeof window.openEvaluationForm === 'function') window.openEvaluationForm();
                    };
                }
            }
        }
    }

    function triggerSyncSoon(delayMs = 200) {
        setTimeout(executeLiveSync, delayMs);
    }

    function startRealtimeSync() {
        if (syncIntervalId) clearInterval(syncIntervalId);
        executeLiveSync();
        // 2.5 second polling interval
        syncIntervalId = setInterval(() => {
            if (!document.hidden) {
                executeLiveSync();
            }
        }, 2500);

        // Immediate poll on tab focus
        window.addEventListener('focus', () => {
            executeLiveSync();
        });
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                executeLiveSync();
            }
        });
    }

    // =========================================================================
    // MODAL WRAPPERS & CLICK HANDLERS
    // =========================================================================

    // Wrapper for openScheduleModal in interview_waiting.html
    window.hrOpenScheduleModal = async function(appId, appName, jobTitle, jobId) {
        const result = await acquireLock(appId, 'SCHEDULE');
        if (!result.success) {
            showConcurrencyAlert(`<strong>${appName}</strong> is currently being scheduled by <strong>${result.locked_by || 'another HR staff member'}</strong>. Please wait until they finish.`);
            return;
        }

        if (typeof window.openScheduleModal === 'function') {
            window.openScheduleModal(appId, appName, jobTitle, jobId);
        }
    };

    // Wrapper for openManageInterviewModal in interview_evaluations.html
    window.hrOpenManageInterviewModal = async function(appId, appName, jobTitle, date, time, interviewer, location) {
        if (lastSyncData && Array.isArray(lastSyncData.ongoing_evaluations)) {
            const ongoing = lastSyncData.ongoing_evaluations.find(ev => String(ev.application_id) === String(appId));
            if (ongoing) {
                showConcurrencyAlert(`Interview for <strong>${appName}</strong> cannot be managed while candidate evaluation is actively ongoing (by <strong>${ongoing.evaluator_name}</strong>).`);
                return;
            }
        }

        const result = await acquireLock(appId, 'RESCHEDULE');
        if (!result.success) {
            showConcurrencyAlert(`Interview for <strong>${appName}</strong> is currently being managed/rescheduled by <strong>${result.locked_by || 'another HR staff member'}</strong>.`);
            return;
        }

        if (typeof window.openManageInterviewModal === 'function') {
            window.openManageInterviewModal(appId, appName, jobTitle, date, time, interviewer, location);
        }
    };

    // Wrapper for openFinalReviewModal in candidate_detail.html & reports.html
    window.hrOpenFinalReviewModal = async function(appId) {
        const result = await acquireLock(appId, 'FINAL_DECISION');
        if (!result.success) {
            showConcurrencyAlert(`Final hiring decision for this candidate is currently being reviewed by <strong>${result.locked_by || 'another HR staff member'}</strong>.`);
            return;
        }

        if (typeof window._doOpenFinalReviewModal === 'function') {
            window._doOpenFinalReviewModal(appId);
        } else if (typeof window.openFinalReviewModal === 'function') {
            window.openFinalReviewModal(appId);
        }
    };

    // Wrapper for closing modals and releasing locks
    window.hrCloseScheduleModal = function(appId) {
        if (appId) {
            releaseLock(appId, 'SCHEDULE');
        }
        if (typeof window.closeScheduleModal === 'function') {
            window.closeScheduleModal();
        }
    };

    window.hrCloseManageInterviewModal = function(appId) {
        if (appId) {
            releaseLock(appId, 'RESCHEDULE');
        }
        if (typeof window.closeManageInterviewModal === 'function') {
            window.closeManageInterviewModal();
        }
    };

    window.hrCloseFinalReviewModal = function(appId) {
        if (appId) {
            releaseLock(appId, 'FINAL_DECISION');
        }
        if (typeof window.closeFinalReviewModal === 'function') {
            window.closeFinalReviewModal();
        }
    };

    function getOngoingEvaluation(appId) {
        if (!lastSyncData || !Array.isArray(lastSyncData.ongoing_evaluations)) return null;
        return lastSyncData.ongoing_evaluations.find(ev => String(ev.application_id) === String(appId)) || null;
    }

    // Expose APIs globally
    window.HRConcurrency = {
        acquireLock,
        acquireBatchLock,
        releaseLock,
        releaseBatchLock,
        showConcurrencyAlert,
        currentLocks,
        triggerSyncSoon,
        executeLiveSync,
        getCSRFToken,
        getOngoingEvaluation
    };

    // Auto-start real-time sync on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startRealtimeSync);
    } else {
        startRealtimeSync();
    }
})();
