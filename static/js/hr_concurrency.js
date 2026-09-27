/**
 * HR Multi-User Concurrency & Action Isolation Controller
 * Prevents simultaneous conflicts across scheduling, rescheduling, evaluation, and final reviews.
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

    const currentLocks = new Map(); // key: targetModel:targetId:actionType -> intervalId

    function showConcurrencyAlert(message) {
        let container = document.getElementById('hr-concurrency-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'hr-concurrency-toast-container';
            container.style.cssText = 'position: fixed; top: 24px; right: 24px; z-index: 99999; display: flex; flex-direction: column; gap: 10px; max-width: 380px; pointer-events: none;';
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
        const csrfToken = getCookie('csrftoken');
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

            const data = await resp.json();
            if (data.success) {
                // Start heartbeat every 30 seconds
                if (currentLocks.has(lockKey)) {
                    clearInterval(currentLocks.get(lockKey));
                }
                const heartbeatId = setInterval(() => {
                    fetch('/hr/api/lock/heartbeat/', {
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
                    }).catch(() => {});
                }, 30000);

                currentLocks.set(lockKey, heartbeatId);
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
            // On network failure, fail open or allow user to proceed
            return { success: true };
        }
    }

    async function releaseLock(targetId, actionType, targetModel = 'Application') {
        const csrfToken = getCookie('csrftoken');
        const lockKey = `${targetModel}:${targetId}:${actionType}`;

        if (currentLocks.has(lockKey)) {
            clearInterval(currentLocks.get(lockKey));
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
        } catch (e) {
            console.error('Error releasing action lock:', e);
        }
    }

    // Auto-release all locks on page unload
    window.addEventListener('beforeunload', function() {
        for (const [key, intervalId] of currentLocks.entries()) {
            clearInterval(intervalId);
            const [targetModel, targetId, actionType] = key.split(':');
            navigator.sendBeacon(
                '/hr/api/lock/release/',
                new Blob([JSON.stringify({ target_model: targetModel, target_id: targetId, action_type: actionType })], { type: 'application/json' })
            );
        }
    });

    // Expose APIs globally
    window.HRConcurrency = {
        acquireLock,
        releaseLock,
        showConcurrencyAlert,
        currentLocks
    };

    // Wrapper for openScheduleModal in interview_waiting.html
    window.hrOpenScheduleModal = async function(appId, appName, jobTitle, jobId) {
        const result = await acquireLock(appId, 'SCHEDULE');
        if (!result.success) {
            showConcurrencyAlert(`<strong>${appName}</strong> is currently being scheduled by <strong>${result.locked_by}</strong>. Please wait until they finish.`);
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
            showConcurrencyAlert(`Interview for <strong>${appName}</strong> is currently being managed/rescheduled by <strong>${result.locked_by}</strong>.`);
            return;
        }

        if (typeof window.openManageInterviewModal === 'function') {
            window.openManageInterviewModal(appId, appName, jobTitle, date, time, interviewer, location);
        }
    };

    // Wrapper for openFinalReviewModal in candidate_detail.html & reports_evaluations.html
    window.hrOpenFinalReviewModal = async function(appId) {
        const result = await acquireLock(appId, 'FINAL_DECISION');
        if (!result.success) {
            showConcurrencyAlert(`Final hiring decision for this candidate is currently being reviewed by <strong>${result.locked_by}</strong>.`);
            return;
        }

        if (typeof window.openFinalReviewModalOriginal === 'function') {
            window.openFinalReviewModalOriginal(appId);
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
})();
