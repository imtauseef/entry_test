function cbtSessionEnded(data) {
    if (data && data.session_ended) {
        window.location.href = "/web/login?cbt_session_ended=1";
        return true;
    }
    return false;
}

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
            paper_finish($("#paper_id").val());
            return;
        }
        jQuery(".countdown").html(minutes + ":" + String(seconds).padStart(2, '0'));
        var count = setInterval(function() {
            if (minutes === 0 && seconds === 0) {
                clearInterval(count);
                paper_finish($("#paper_id").val());
                return;
            }
            if (seconds === 0) {
                minutes--;
                seconds = 59;
            } else {
                seconds--;
            }
            jQuery(".countdown").html(
                minutes + ":" + String(seconds).padStart(2, '0'));
        }, 1000);
    }

    $.ajax({
        url: "/cbt/paper/currentState",
        type: "GET",
        dataType: "json",
        contentType: false,
        processData: false,
        success: function(data) {
            if (cbtSessionEnded(data)) {
                return;
            }
            if (data.paper_state) {
                window.location.href = "/cbt/paper/finish/page";
                return;
            }
            if (!data.paper_started) {
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
            success: function(data) {
                cbtSessionEnded(data);
            },
            error: function(data) {}
        });
    }, 1000 * 30 * 1);

    window.addEventListener('contextmenu', function (e) {
        e.preventDefault();
    }, false);
});

document.addEventListener('click', function(event) {
    var target = event.target.nodeType === 1
        ? event.target
        : event.target.parentElement;
    var button = target && target.closest('.cbt-nav-feedback');
    if (!button) {
        return;
    }
    var pager = button.closest('.cbt-paginate');
    if (!pager) {
        return;
    }
    var questions = pager.querySelectorAll('.items .cbt-question');
    var question = Array.prototype.find.call(questions, function(item) {
        return window.getComputedStyle(item).display !== 'none';
    }) || questions[0];
    if (!question) {
        return;
    }

    var feedbackText = question.getAttribute('data-feedback-text') || '';
    question = $(question);
    var feedbackTypeId = String(question.attr('data-feedback-type-id') || '');
    button.classList.toggle(
        'has-feedback', Boolean(feedbackTypeId || feedbackText));
    $('#cbt_feedback_question_id').val(question.attr('data-question-id'));
    $('#cbt_feedback_text').val(feedbackText);
    $('input[name="cbt_feedback_type"]').prop('checked', false);
    if (feedbackTypeId) {
        $('input[name="cbt_feedback_type"]').filter(function() {
            return String(this.value) === feedbackTypeId;
        }).prop('checked', true);
    }
    $('#cbt_feedback_status').text('');
    updateFeedbackTextHint();
    openQuestionFeedback();
});

function updateFeedbackTextHint() {
    var isOtherValue = String(
        $('input[name="cbt_feedback_type"]:checked')
            .attr('data-is-other') || '').toLowerCase();
    var otherSelected = isOtherValue === 'true' || isOtherValue === '1';
    $('#cbt_feedback_text_hint').text(otherSelected
        ? 'Please describe the concern selected as Other.'
        : 'Select Other to describe a different concern, or add details to your feedback.');
    $('#cbt_feedback_text').prop('required', otherSelected);
}

function openQuestionFeedback() {
    var modal = document.getElementById('cbt_question_feedback');
    if (!modal) {
        return;
    }

    if (window.M && window.M.Modal) {
        var instance = window.M.Modal.getInstance(modal) ||
            window.M.Modal.init(modal, {dismissible: true});
        instance.open();
        return;
    }

    var $modal = $(modal);
    if (typeof $modal.modal === 'function') {
        if (!$modal.data('modal')) {
            $modal.modal({dismissible: true});
        }
        $modal.modal('open');
        return;
    }

    if (!$('.cbt-feedback-backdrop').length) {
        $('<div class="cbt-feedback-backdrop" aria-hidden="true"></div>')
            .insertBefore($modal);
    }
    $modal.addClass('cbt-feedback-fallback-open')
        .attr('aria-hidden', 'false');
    $('body').addClass('cbt-feedback-fallback-active');
}

function closeQuestionFeedback() {
    var modal = document.getElementById('cbt_question_feedback');
    if (!modal) {
        return;
    }

    if (window.M && window.M.Modal) {
        var instance = window.M.Modal.getInstance(modal);
        if (instance) {
            instance.close();
            return;
        }
    }

    var $modal = $(modal);
    if (typeof $modal.modal === 'function' && $modal.data('modal')) {
        $modal.modal('close');
        return;
    }

    $modal.removeClass('cbt-feedback-fallback-open')
        .attr('aria-hidden', 'true');
    $('.cbt-feedback-backdrop').remove();
    $('body').removeClass('cbt-feedback-fallback-active');
}

$(document).on('change', 'input[name="cbt_feedback_type"]', updateFeedbackTextHint);
$(document).on('click', '#cbt_question_feedback .modal-close', function(event) {
    if ($('.cbt-feedback-fallback-open').length) {
        event.preventDefault();
        closeQuestionFeedback();
    }
});
$(document).on('click', '.cbt-feedback-backdrop', closeQuestionFeedback);
$(document).on('keydown', function(event) {
    if (event.key === 'Escape' && $('.cbt-feedback-fallback-open').length) {
        closeQuestionFeedback();
    }
});

function submitQuestionFeedback(clearFeedback) {
    var formData = new FormData();
    var selectedType = $('input[name="cbt_feedback_type"]:checked');
    var feedbackTypeId = selectedType.val();
    var feedbackText = $('#cbt_feedback_text').val().trim();
    var isOtherValue = String(selectedType.attr('data-is-other') || '')
        .toLowerCase();
    if (!clearFeedback && !feedbackTypeId && !feedbackText) {
        $('#cbt_feedback_status').text(
            'Select a feedback option or enter additional details.');
        return;
    }
    if (!clearFeedback &&
            (isOtherValue === 'true' || isOtherValue === '1') &&
            !feedbackText) {
        $('#cbt_feedback_status').text(
            'Please describe the concern when selecting Other.');
        return;
    }
    formData.append('paper_id', $('#paper_id').val());
    formData.append('question_id', $('#cbt_feedback_question_id').val());
    formData.append('csrf_token', $('#cbt_feedback_csrf').val());
    formData.append(
        'feedback_type_id', clearFeedback ? '' : (feedbackTypeId || ''));
    formData.append(
        'feedback_text',
        clearFeedback ? '' : feedbackText);

    var button = $('#cbt_feedback_save, #cbt_feedback_clear');
    button.prop('disabled', true);
    $('#cbt_feedback_status').text('Saving feedback...');
    $.ajax({
        url: '/cbt/rec/feedback',
        type: 'POST',
        dataType: 'json',
        data: formData,
        contentType: false,
        processData: false,
        success: function(data) {
            if (data.error) {
                $('#cbt_feedback_status').text(data.error);
                return;
            }
            var question = $('.cbt-question').filter(function() {
                return String($(this).attr('data-question-id')) ===
                    String($('#cbt_feedback_question_id').val());
            });
            question.attr(
                'data-feedback-type-id',
                clearFeedback ? '' : (feedbackTypeId || ''));
            question.attr(
                'data-feedback-text',
                clearFeedback ? '' : $('#cbt_feedback_text').val());
            $('.cbt-nav-feedback').toggleClass(
                'has-feedback',
                !clearFeedback && Boolean(feedbackTypeId || $('#cbt_feedback_text').val()));
            $('#cbt_feedback_status').text(data.message);
            closeQuestionFeedback();
        },
        error: function() {
            $('#cbt_feedback_status').text(
                'Unable to save feedback. Please try again.');
        },
        complete: function() {
            button.prop('disabled', false);
        }
    });
}

$(document).on('click', '#cbt_feedback_save', function() {
    submitQuestionFeedback(false);
});

$(document).on('click', '#cbt_feedback_clear', function() {
    submitQuestionFeedback(true);
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
            if (cbtSessionEnded(data)) {
                return;
            }
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
           if (cbtSessionEnded(data)) {
               return;
           }
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
            if (cbtSessionEnded(data)) {
                return;
            }
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
var theorySaveTimers = {};

function rec_theory_answer(question, subject, paper, answer, immediate) {
    var page = '';
    $("#" + subject + '_' + question).remove();
    $(".pageNumbers").children('a').each(function() {
        var element = $(this);
        if ($(this).prop('class') == 'active') {
            page = element[0].dataset.page;
        }
    });
    clearTimeout(theorySaveTimers[question]);
    theorySaveTimers[question] = setTimeout(function() {
        var formData = new FormData();
        formData.append('question_id', question);
        formData.append('page', page);
        formData.append('subject_id', subject);
        formData.append('paper_id', paper);
        formData.append('answer', 0);
        formData.append('answer_no', 0);
        formData.append('theory_answer', answer);
        $.ajax({
            url: "/cbt/rec/answer",
            type: "POST",
            dataType: "json",
            data: formData,
            contentType: false,
            processData: false,
            success: function(data) {
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
    }, immediate ? 0 : 500);
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
                if (data.mark_review_list[i].is_theory) {
                    $("#mark_body").append("Answer: ");
                    $("#mark_body").append(data.mark_review_list[i].theory_answer || "(not answered)");
                    $("#mark_body").append("<br/>");
                } else {
                    for (var j = 0; j < data.mark_review_list[i].options.length; j++) {
                        var rec_options = "<div id='view-radio-buttons'><p><label> <input class='with-gap' name='group3' type='radio' onchange='rec_answer()'/> </label></p><span></span></div>";
                        $("#mark_body").append(j + 1 + "." + rec_options);
                        $("#mark_body").append(data.mark_review_list[i].options[j].option);
                        $("#mark_body").append("<br/>");
                    }
                }
            }
        },
        error: function(data) {
            console.log('error');
            console.log(data.message);
        }
    });
}
