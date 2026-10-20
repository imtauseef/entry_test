/* Initialize Materialize components used by the CBT portal (modals + non-linear stepper). */
$(document).ready(function () {
    if (typeof $.fn.modal === 'function') {
        $('.modal').modal();
    }
    if (typeof $.fn.activateStepper === 'function') {
        $('.stepper').activateStepper();
    }
});
