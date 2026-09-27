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
                    locksMap.set(`${lock.target_id}:${lock.action_type}`, lock);
                    // General lookup by target_id
                    locksMap.set(String(lock.target_id), lock);
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

            // Remember original state
            if (!el.hasAttribute('data-orig-html')) {
                el.setAttribute('data-orig-html', el.innerHTML);
            }
            if (!el.hasAttribute('data-orig-style')) {
                el.setAttribute('data-orig-style', el.getAttribute('style') || '');
            }
            if (!el.hasAttribute('data-orig-onclick')) {
                el.setAttribute('data-orig-onclick', el.getAttribute('onclick') || '');
            }

            const specificLock = locksMap.get(`${candId}:${actionType}`) || (actionType !== 'EVALUATE' ? locksMap.get(String(candId)) : null);

            if (actionType === 'EVALUATE') {
                const ongoingEval = ongoingEvalsMap.get(String(candId));
                if (ongoingEval) {
                    if (ongoingEval.evaluator_id !== currentUserId) {
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
                        el.style.cssText = 'background: #2d5a27; color: #ffffff !important; border: 1.5px solid transparent; padding: 6px 14px; border-radius: 8px; font-weight: 700; font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px;';
                        el.innerHTML = '<i class="fas fa-clipboard-check"></i> <span>Continue Evaluation</span>';
                        if (el.tagName.toLowerCase() === 'a') {
                            el.setAttribute('href', `/hr/candidates/applicant/${candId}/?evaluate=true`);
                        }
                    }
                } else {
                    // Normal Evaluate button
                    el.disabled = false;
                    el.classList.remove('disabled');
                    el.style.cssText = el.getAttribute('data-orig-style');
                    el.innerHTML = el.getAttribute('data-orig-html');
                    const origClick = el.getAttribute('data-orig-onclick');
                    if (origClick) el.setAttribute('onclick', origClick);
                }
            } else if (specificLock) {
                // Button is locked by another user!
                el.disabled = true;
                el.classList.add('disabled');
                el.style.cssText = 'background: #f1f5f9; color: #64748b !important; border-color: #cbd5e1; cursor: not-allowed; opacity: 0.85; padding: 6px 14px; border-radius: 8px; font-weight: 700; font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px;';
                el.innerHTML = `<i class="fas fa-lock"></i> <span>Locked (${specificLock.user_name})</span>`;
                el.title = `Currently being handled by ${specificLock.user_name}.`;
            } else {
                // Button is free
                if (el.disabled && el.classList.contains('disabled')) {
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

        // 5. Candidate Detail Page Live Evaluation Form Hiding (Item 2)
        const candidateDetailContainer = document.getElementById('eval-form-card');
        const candidateLockedCard = document.getElementById('eval-locked-card');
        const candidatePendingCard = document.getElementById('eval-pending-card');
        const heroEvaluateBtn = document.querySelector('.hero-actions-stack .btn-evaluate');

        if (candidateDetailContainer) {
            const pageAppId = candidateDetailContainer.getAttribute('data-app-id') || document.getElementById('schedApplicantId')?.value;
            const currentEval = pageAppId ? ongoingEvalsMap.get(String(pageAppId)) : null;

            if (currentEval && currentEval.evaluator_id !== currentUserId) {
                // Candidate is being evaluated by ANOTHER evaluator -> HIDE FORM!
                candidateDetailContainer.style.setProperty('display', 'none', 'important');
                if (candidatePendingCard) candidatePendingCard.style.display = 'none';
                if (candidateLockedCard) {
                    candidateLockedCard.style.display = 'block';
                    const lockedDesc = candidateLockedCard.querySelector('p strong');
                    if (lockedDesc) lockedDesc.textContent = currentEval.evaluator_name;
                }
                if (heroEvaluateBtn) {
                    heroEvaluateBtn.disabled = true;
                    heroEvaluateBtn.classList.add('disabled');
                    heroEvaluateBtn.style.cssText = 'background: #f1f5f9; color: #64748b !important; border: 1px solid #cbd5e1; cursor: not-allowed;';
                    heroEvaluateBtn.innerHTML = `<i class="fas fa-lock"></i> <span>In Evaluation (${currentEval.evaluator_name})</span>`;
                }
            } else if (currentEval && currentEval.evaluator_id === currentUserId) {
                // Current user is the evaluator
                if (candidateLockedCard) candidateLockedCard.style.display = 'none';
                if (heroEvaluateBtn) {
                    heroEvaluateBtn.disabled = false;
                    heroEvaluateBtn.classList.remove('disabled');
                    heroEvaluateBtn.innerHTML = '<i class="fas fa-clipboard-check"></i> <span>Continue Evaluation</span>';
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
        getCSRFToken
    };

    // Auto-start real-time sync on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startRealtimeSync);
    } else {
        startRealtimeSync();
    }
})();
