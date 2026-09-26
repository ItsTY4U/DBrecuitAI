/**
 * HR Dynamic, Real-time & Reactive Notifications Controller
 * Universal controller across all 5 HR navigation views.
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

    let activeCategory = 'all';

    window.toggleNotificationDropdown = function(event) {
        if (event) event.stopPropagation();
        const dropdown = document.getElementById('notif-dropdown');
        const bellBtn = document.getElementById('notif-bell-btn');
        if (!dropdown) return;

        const isCurrentlyOpen = dropdown.style.display !== 'none';
        if (isCurrentlyOpen) {
            dropdown.style.display = 'none';
            if (bellBtn) bellBtn.setAttribute('aria-expanded', 'false');
        } else {
            dropdown.style.display = 'block';
            if (bellBtn) bellBtn.setAttribute('aria-expanded', 'true');
            // Reapply current category filter
            applyCategoryFilter(activeCategory);
        }
    };

    window.filterNotifCategory = function(event, category) {
        if (event) event.stopPropagation();
        activeCategory = category || 'all';

        // Update active tab buttons
        document.querySelectorAll('.notif-cat-tab').forEach(tab => {
            if (tab.getAttribute('data-cat') === activeCategory) {
                tab.classList.add('active');
            } else {
                tab.classList.remove('active');
            }
        });

        applyCategoryFilter(activeCategory);
    };

    function applyCategoryFilter(category) {
        const list = document.getElementById('notif-dropdown-list');
        if (!list) return;

        const items = list.querySelectorAll('.notif-item');
        const catEmpty = document.getElementById('notif-category-empty');
        const defaultEmpty = document.getElementById('notif-empty-state');
        let visibleCount = 0;

        items.forEach(item => {
            const itemCat = item.getAttribute('data-category') || 'system';
            const isRead = item.getAttribute('data-is-read') === 'true';

            let shouldShow = false;
            if (category === 'all') {
                shouldShow = true;
            } else if (category === 'unread') {
                shouldShow = !isRead || item.classList.contains('is-unread');
            } else {
                shouldShow = (itemCat === category);
            }

            if (shouldShow) {
                item.style.display = 'flex';
                visibleCount++;
            } else {
                item.style.display = 'none';
            }
        });

        if (catEmpty) {
            if (items.length > 0 && visibleCount === 0) {
                catEmpty.style.display = 'flex';
            } else {
                catEmpty.style.display = 'none';
            }
        }
    }

    window.markAllNotificationsRead = function(event) {
        if (event) event.stopPropagation();
        fetch('/hr/api/notifications/mark-read/', {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': getCookie('csrftoken'),
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ all: true })
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                const bell = document.getElementById('notif-bell-btn');
                const badge = document.getElementById('notif-badge');
                const pill = document.getElementById('notif-unread-pill');
                if (bell) bell.classList.remove('has-unread');
                if (badge) badge.style.display = 'none';
                if (pill) pill.textContent = 'All caught up';

                document.querySelectorAll('.notif-item').forEach(el => {
                    el.classList.remove('is-unread');
                    el.setAttribute('data-is-read', 'true');
                    const dot = el.querySelector('.notif-item-unread-dot');
                    if (dot) dot.remove();
                });

                if (activeCategory === 'unread') {
                    applyCategoryFilter('unread');
                }
            }
        })
        .catch(err => console.warn('Failed to mark notifications read:', err));
    };

    window.handleNotificationClick = function(event, itemEl) {
        if (event) event.stopPropagation();
        const notifId = itemEl.getAttribute('data-notif-id');
        const targetLink = itemEl.getAttribute('data-link');

        // Mark individual notification as read
        if (notifId && (itemEl.classList.contains('is-unread') || itemEl.getAttribute('data-is-read') === 'false')) {
            fetch('/hr/api/notifications/mark-read/', {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCookie('csrftoken'),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ notification_id: notifId })
            }).finally(() => {
                if (targetLink) window.location.href = targetLink;
            });
        } else if (targetLink) {
            window.location.href = targetLink;
        }
    };

    // Close notification dropdown when clicking outside
    document.addEventListener('click', function(e) {
        const wrapper = document.getElementById('notif-wrapper');
        const dropdown = document.getElementById('notif-dropdown');
        if (wrapper && dropdown && !wrapper.contains(e.target)) {
            dropdown.style.display = 'none';
            const bellBtn = document.getElementById('notif-bell-btn');
            if (bellBtn) bellBtn.setAttribute('aria-expanded', 'false');
        }
    });

    // Close notification dropdown on Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const dropdown = document.getElementById('notif-dropdown');
            if (dropdown && dropdown.style.display !== 'none') {
                dropdown.style.display = 'none';
                const bellBtn = document.getElementById('notif-bell-btn');
                if (bellBtn) bellBtn.setAttribute('aria-expanded', 'false');
            }
        }
    });

    // Real-time polling function (every 15 seconds)
    function pollNotifications() {
        fetch('/hr/api/notifications/', {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                const bell = document.getElementById('notif-bell-btn');
                const badge = document.getElementById('notif-badge');
                const pill = document.getElementById('notif-unread-pill');
                const list = document.getElementById('notif-dropdown-list');

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

                if (list && data.notifications && data.notifications.length > 0) {
                    let html = '';
                    data.notifications.forEach(n => {
                        let iconHtml = '<i class="fas fa-bell"></i>';
                        if (n.type === 'NEW_APPLICATION') {
                            iconHtml = '<i class="fas fa-user-plus"></i>';
                        } else if (n.type === 'VIDEO_INTERVIEW_COMPLETED') {
                            iconHtml = '<i class="fas fa-video"></i>';
                        } else if (n.type === 'INTERVIEW_SCHEDULED') {
                            iconHtml = '<i class="fas fa-calendar-check"></i>';
                        } else if (n.type === 'EVALUATION_COMPLETED') {
                            iconHtml = '<i class="fas fa-clipboard-check"></i>';
                        } else if (n.type === 'HR_ACTION') {
                            iconHtml = '<i class="fas fa-user-gear"></i>';
                        }

                        const unreadClass = !n.is_read ? 'is-unread' : '';
                        const unreadDot = !n.is_read ? '<span class="notif-item-unread-dot"></span>' : '';
                        const cat = n.category || 'system';

                        html += `
                        <div class="notif-item ${unreadClass}"
                             data-notif-id="${n.id}"
                             data-category="${cat}"
                             data-is-read="${n.is_read ? 'true' : 'false'}"
                             data-link="${n.link}"
                             onclick="handleNotificationClick(event, this)">
                            <div class="notif-item-icon notif-icon-${n.type.toLowerCase()}">
                                ${iconHtml}
                            </div>
                            <div class="notif-item-body">
                                <div class="notif-item-title-row">
                                    <h5 class="notif-item-title">${n.title}</h5>
                                    <span class="notif-item-time">${n.time_ago}</span>
                                </div>
                                <p class="notif-item-msg">${n.message}</p>
                            </div>
                            ${unreadDot}
                        </div>`;
                    });

                    html += `
                    <div class="notif-empty-state" id="notif-category-empty" style="display: none;">
                        <i class="fas fa-inbox"></i>
                        <p>No notifications in this category.<br><span style="font-size:12px; color:#94a3b8;">Check other categories or "All".</span></p>
                    </div>`;

                    list.innerHTML = html;
                    applyCategoryFilter(activeCategory);
                }
            }
        })
        .catch(err => console.debug('Notifications polling:', err));
    }

    // Initialize polling interval once
    if (!window.__hrNotifPollInterval) {
        window.__hrNotifPollInterval = setInterval(pollNotifications, 15000);
    }
})();
