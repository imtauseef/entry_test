$(document).ready(function () {
    if (!$("#timer").length) {
        return;
    }
    function parseTime(s) {
        var part = s.match(/(\d+):(\d+)(?: )?(am|pm)?/i);
        var hh = parseInt(part[1], 10);
        var mm = parseInt(part[2], 10);
        var ap = part[3] ? part[3].toUpperCase() : null;
        if (ap === "AM") {
            if (hh == 12) {
                hh = 0;
            }
        }
        if (ap === "PM") {
            if (hh != 12) {
                hh += 12;
            }
        }
        var currentYearMonthDay = new Date();
        return new Date(currentYearMonthDay.getFullYear(), currentYearMonthDay.getMonth(), currentYearMonthDay.getDate(), hh, mm);
    }
    var interval = setInterval(function () {
        var startEl = document.getElementById('paper_start');
        var startTimeEl = document.getElementById('paper_start_time');
        if (!startEl || !startTimeEl) {
            clearInterval(interval);
            return;
        }
        var timer = parseTime($("#timer").val());
        var currentTime = new Date();
        if (timer < currentTime) {
            startEl.style.display = 'block';
            startTimeEl.style.display = 'none';
        } else {
            startEl.style.display = 'none';
            startTimeEl.style.display = 'block';
        }
    }, 1000);
    window.addEventListener('contextmenu', function (e) {
        e.preventDefault();
    }, false);
});
