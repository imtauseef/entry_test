odoo.define ('cbt.fetch_participant', function (require) {
    "use strict";
    
    var core = require ('web.core');
    var ListController = require ('web.ListController');
    ListController.include ({
       renderButtons: function ($node) {
       this._super.apply (this, arguments);
           if (this.$buttons) {
             this.$buttons.find ('.o_list_fetch_participant'). click (this.proxy ('action_def'));
           }
        },
    
        // ------------------------------------------------ --------------------------
        // Define Handler for new Custom Button
        // -------------- -------------------------------------------------- ----------
    
    //    / **
    //     * @private
    //     * @param {MouseEvent} event
    //     * /
        action_def: function (e) {
            var self = this;
            var model_name = this.model.get (this.handle) .getContext () ['active_model'];
                this._rpc ({
                        model: 'cbt.participant',
                        method: 'fetch_participant',
                        args: [1],
                    }). then (function (result) {
                        if(result['status']=='updated'){
                            alert('Participants Synchronized!')
                          
                            window.location.reload()
                        }else{
                            console.error(result['error'])
                            alert(result['msg'])
                        }
                    });
       },
    });
    });