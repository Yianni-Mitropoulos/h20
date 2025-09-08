// handler_attacher.js
document.addEventListener('DOMContentLoaded', function () {
    // Prev
    document.querySelectorAll('button.prev-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (typeof window.prev === 'function') {
                // optional: skip when disabled/aria-disabled
                if (btn.disabled || (btn.getAttribute('aria-disabled') || 'false').toLowerCase() === 'true') return;
                window.prev.call(this);
            }
        });
    });

    // Next
    document.querySelectorAll('button.next-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (typeof window.next === 'function') {
                if (btn.disabled || (btn.getAttribute('aria-disabled') || 'false').toLowerCase() === 'true') return;
                window.next.call(this);
            }
        });
    });

    // Copy
    document.querySelectorAll('button.copy-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (typeof window.copyToClipboard === 'function') {
                if (btn.disabled || (btn.getAttribute('aria-disabled') || 'false').toLowerCase() === 'true') return;
                window.copyToClipboard.call(this);
            }
        });
    });
});
