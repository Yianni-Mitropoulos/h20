document.addEventListener('click', function (e) {
    var btn;

    btn = e.target.closest('button.prev');
    if (btn && typeof window.prev === 'function') {
        window.prev.call(btn);
        return;
    }

    btn = e.target.closest('button.next');
    if (btn && typeof window.next === 'function') {
        window.next.call(btn);
        return;
    }

    btn = e.target.closest('button.copy-btn');
    if (btn && typeof window.copyToClipboard === 'function') {
        window.copyToClipboard.call(btn);
        return;
    }
});
