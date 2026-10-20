$(document).ready(function() {
    var timer2 = "";
    var minutes = 0;
    var seconds = 0;
    var countdownStarted = false;

    function parseRemaining(value) {
        var match = (typeof value === 'string') ? value.trim().match(/^(\d+):(\d+)$/) : null;
        if (match) {
            minutes = parseInt(match[1], 10);
            seconds = parseInt(match[2], 10);
        } else {
            var duration = parseInt($("#duration").val(), 10);
            minutes = isNaN(duration) ? 0 : duration;
            seconds = 0;
        }
    }

    function startCountdown() {
        if (countdownStarted) {
            return;
        }
        countdownStarted = true;
        if (minutes <= 0 && seconds <= 0) {
            window.location.href = "/cbt/paper/finish/page";
            return;
        }
        jQuery(".countdown").html(minutes + ":" + seconds);
        var count = setInterval(function() {
            if (parseInt(minutes) < 0) {
                clearInterval(count);
            } else {
                jQuery(".countdown").html(minutes + ":" + seconds);
                if (seconds == 0) {
                    minutes--;
                    seconds = 60;
                    if (minutes == 0) {
                        window.location.href = "/cbt/paper/finish/page";
                    }
                }
                seconds--;
            }
        }, 1000);
    }

    $.ajax({
        url: "/cbt/paper/currentState",
        type: "GET",
        dataType: "json",
        contentType: false,
        processData: false,
        success: function(data) {
            if (data.paper_state) {
                window.location.href = "/cbt/paper/finish/page";
                return;
            }
            console.log(data);
            parseRemaining(data.time_remaining);
            startCountdown();
            $(function() {
                $(".paginate").paginga({
                    page: data.current_q ? parseInt(data.current_q) : 1
                });
            });
            $(".previous-step").text("Prev");
            $(".next-step").text("Next Section");
        },
        error: function(data) {
            parseRemaining("");
            startCountdown();
        }
    });
    var interval = setInterval(function() {
        if (!countdownStarted) {
            return;
        }
        timer2 = minutes + ':' + seconds;
        var formData = new FormData();
        formData.append('time', timer2);
        $.ajax({
            url: "/cbt/time/remaining",
            type: "POST",
            dataType: "json",
            data: formData,
            // beforeSend: function(){ showNotify('Please wait !','warning','top-right');},
            contentType: false,
            processData: false,
            success: function(data) {},
            error: function(data) {}
        });
    }, 1000 * 30 * 1);

    window.addEventListener('contextmenu', function (e) {
        e.preventDefault();
    }, false);
});
function record_time(){

     timer5 = jQuery(".countdown").text();
        var formData = new FormData();
        formData.append('time', timer5);
        $.ajax({
            url: "/cbt/time/remaining",
            type: "POST",
            dataType: "json",
            data: formData,
            // beforeSend: function(){ showNotify('Please wait !','warning','top-right');},
            contentType: false,
            processData: false,
            success: function(data) {
            window.location.href = "/cbt/paper/review";
            },
            error: function(data) {}
        });
    }
function record_time_rev(){

     timer5 = jQuery(".countdown").text();
        var formData = new FormData();
        formData.append('time', timer5);
        $.ajax({
            url: "/cbt/time/remaining",
            type: "POST",
            dataType: "json",
            data: formData,
            // beforeSend: function(){ showNotify('Please wait !','warning','top-right');},
            contentType: false,
            processData: false,
            success: function(data) {
           // window.location.href = "/cbt/paper";
            },
            error: function(data) {}
        });
    }
function record_time_old(){

     timer5 = jQuery(".countdown").text();
        var formData = new FormData();
        formData.append('time', timer5);
        $.ajax({
            url: "/cbt/time/remaining",
            type: "POST",
            dataType: "json",
            data: formData,
            // beforeSend: function(){ showNotify('Please wait !','warning','top-right');},
            contentType: false,
            processData: false,
            success: function(data) {
            window.location.href = "/cbt/paper";
            },
            error: function(data) {}
        });
    }

function rec_answer(question, subject, paper, answer_no, answer) {
    console.log(question);
    console.log(subject);
    console.log(paper);
    console.log(answer_no);
    console.log(answer);
    var formData = new FormData();
    var page = '';
    $("#"+subject+'_'+question).remove();
    $(".pageNumbers").children('a').each(function() {
        var element = $(this);
        var activeOrNot = $(this).prop('class');
        if (activeOrNot == 'active') {
            page = element[0].dataset.page;
//            debugger;
//            element.addClass("green");
        }
    });
    formData.append('question_id', question);
    formData.append('page', page);
    formData.append('subject_id', subject);
    formData.append('paper_id', paper);
    formData.append('answer', answer);
    formData.append('answer_no', answer_no);
    $.ajax({
        url: "/cbt/rec/answer",
        type: "POST",
        dataType: "json",
        data: formData,
        // beforeSend: function(){ showNotify('Please wait !','warning','top-right');},
        contentType: false,
        processData: false,
        success: function(data) {
            console.log(data.message);
            console.log(data.total_q);
            console.log(data.answered);
            jQuery("#total").html(data.total_q);
            jQuery("#answered").html(data.answered);
            jQuery("#total_finish_paper").html(data.total_q);
            jQuery("#total_answered_paper").html(data.answered);
        },
        error: function(data) {
            console.log('error');
            console.log(data.message);
            alert("Network Issue");
        }
    });
}
function paper_finish(paper) {
    var formData = new FormData();
    formData.append('paper_id', paper);
    $.ajax({
        url: "/cbt/paper/finish",
        type: "POST",
        dataType: "json",
        data: formData,
        // beforeSend: function(){ showNotify('Please wait !','warning','top-right');},
        contentType: false,
        processData: false,
        success: function(data) {
            window.location.href = "/cbt/paper/finish/page";
        },
        error: function(data) {
            console.log(data.message)
        }
    });
}

function mark_review(question, subject, paper, state) {
    var formData = new FormData();
    formData.append('question_id', question);
    formData.append('subject_id', subject);
    formData.append('paper_id', paper);
    formData.append('mark', state.checked);
    $.ajax({
        url: "/cbt/rec/mark_review",
        type: "POST",
        dataType: "json",
        data: formData,
        // beforeSend: function(){ showNotify('Please wait !','warning','top-right');},
        contentType: false,
        processData: false,
        success: function(data) {
            //  console.log(data.message)
        },
        error: function(data) {
            console.log('error');
            console.log(data.message);

        }
    });
}

function review_marked_questions(paper) {
    var formData = new FormData();
    formData.append('paper_id', paper);
    $.ajax({
        url: "/cbt/rec/review/marked/questions",
        type: "POST",
        dataType: "json",
        data: formData,
        // beforeSend: function(){ showNotify('Please wait !','warning','top-right');},
        contentType: false,
        processData: false,
        success: function(data) {
            $("#mark_body").empty();
            for (var i = 0; i < data.mark_review_list.length; i++) {
                $("#mark_body").append("Q. ");
                $("#mark_body").append(data.mark_review_list[i].question);
                $("#mark_body").append("(" + data.mark_review_list[i].subject + ")");
                $("#mark_body").append("<br/>");
                console.log(data.mark_review_list[i].question);
                for (var j = 0; j < data.mark_review_list[i].options.length; j++) {
                    var rec_options = "<div id='view-radio-buttons'><p><label> <input class='with-gap' name='group3' type='radio' onchange='rec_answer()'/> </label></p><span></span></div>";
                    $("#mark_body").append(j + 1 + "." + rec_options);
                    $("#mark_body").append(data.mark_review_list[i].options[j].option);
                    $("#mark_body").append("<br/>");
                }
            }
        },
        error: function(data) {
            console.log('error');
            console.log(data.message);
        }
    });
}


