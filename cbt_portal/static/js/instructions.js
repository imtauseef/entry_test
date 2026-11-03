(function () {
    function initializeTestAvailability() {
        var startEl = document.getElementById('paper_start');
        var startTimeEl = document.getElementById('paper_start_time');
        var errorEl = document.getElementById('paper_error');
        if (!startEl || !startTimeEl || !errorEl) {
            return;
        }

        var checking = false;
        function updateAvailability() {
            if (checking) {
                return;
            }
            checking = true;
            fetch('/cbt/test/availability', {
                credentials: 'same-origin',
                cache: 'no-store',
                headers: {'Accept': 'application/json'},
            }).then(function (response) {
                if (!response.ok) {
                    throw new Error('Availability request failed: ' + response.status);
                }
                return response.json();
            }).then(function (data) {
                if (data.session_ended) {
                    window.location.assign('/web/login?redirect=%2Fcbt%2Fhome');
                    return;
                }
                if (data.available) {
                    startEl.style.display = 'block';
                    startTimeEl.style.display = 'none';
                    errorEl.style.display = 'none';
                    return;
                }
                startEl.style.display = 'none';
                startTimeEl.style.display = 'none';
                errorEl.style.display = 'block';
                errorEl.textContent =
                    'Waiting for the administrator to start the test.';
            }).catch(function (error) {
                console.error('Unable to check test availability:', error);
                errorEl.style.display = 'block';
                errorEl.textContent =
                    'Unable to check test availability. Please try again.';
            }).finally(function () {
                checking = false;
            });
        }

        updateAvailability();
        window.setInterval(updateAvailability, 2000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener(
            'DOMContentLoaded', initializeTestAvailability);
    } else {
        initializeTestAvailability();
    }

    window.addEventListener('contextmenu', function (event) {
        event.preventDefault();
    }, false);
}());
