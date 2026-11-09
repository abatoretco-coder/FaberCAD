//! FABER's small UI surface for external MCP clients such as Codex.
//!
//! FABER never runs a model or owns an agent conversation. The desktop application only
//! exposes its deterministic control channel and explains how a separate MCP client connects.

use crate::ui_kit::BackingTooltipExt as _;
use crate::ui_kit::{self, Button};
use crate::{SolveApp, scenario};

/// Production FABER excludes the legacy implementation at compilation, not just in layout.
pub(crate) const EMBEDDED_ASSISTANT: bool = cfg!(any(test, feature = "legacy-embedded-assistant"));

/// External MCP requests do not require an embedded chat turn or backend.
pub(crate) fn with_tool_request<T>(
    app: &mut SolveApp,
    active: Option<&std::sync::Arc<std::sync::atomic::AtomicBool>>,
    run: impl FnOnce(&mut SolveApp) -> T,
) -> T {
    #[cfg(any(test, feature = "legacy-embedded-assistant"))]
    {
        crate::agent_chat::with_tool_request(app, active, run)
    }
    #[cfg(not(any(test, feature = "legacy-embedded-assistant")))]
    {
        let _ = active;
        run(app)
    }
}

pub(crate) fn tool_space(app: &SolveApp, available: egui::Rect) -> egui::Rect {
    #[cfg(any(test, feature = "legacy-embedded-assistant"))]
    {
        crate::agent_chat::tool_space(app, available)
    }
    #[cfg(not(any(test, feature = "legacy-embedded-assistant")))]
    {
        let _ = app;
        available
    }
}

pub(crate) fn left_inset(app: &SolveApp, available: egui::Rect) -> f32 {
    #[cfg(any(test, feature = "legacy-embedded-assistant"))]
    {
        crate::agent_chat::left_inset(app, available)
    }
    #[cfg(not(any(test, feature = "legacy-embedded-assistant")))]
    {
        let _ = (app, available);
        0.0
    }
}

pub(crate) fn owns_keyboard_input(app: &mut SolveApp, ctx: &egui::Context) -> bool {
    #[cfg(any(test, feature = "legacy-embedded-assistant"))]
    {
        crate::agent_chat::owns_keyboard_input(app, ctx)
    }
    #[cfg(not(any(test, feature = "legacy-embedded-assistant")))]
    {
        let _ = (app, ctx);
        false
    }
}

pub(crate) fn app_bar_button_shown(app: &SolveApp) -> bool {
    #[cfg(any(test, feature = "legacy-embedded-assistant"))]
    {
        crate::agent_chat::app_bar_button_shown(app)
    }
    #[cfg(not(any(test, feature = "legacy-embedded-assistant")))]
    {
        let _ = app;
        false
    }
}

pub(crate) fn assistant_busy(app: &SolveApp) -> bool {
    #[cfg(any(test, feature = "legacy-embedded-assistant"))]
    {
        app.agent_chat.state() == crate::agent_chat::State::Busy
    }
    #[cfg(not(any(test, feature = "legacy-embedded-assistant")))]
    {
        let _ = app;
        false
    }
}

const MCP_COMMAND: &str = "solidcraft-cli mcp";

pub fn page(app: &mut SolveApp, ui: &mut egui::Ui) {
    ui_kit::settings_page(ui, |ui| {
        ui_kit::settings_heading(ui, crate::i18n::tr("faber.external_control.title"), crate::i18n::tr("faber.external_control.intro"));

        ui_kit::settings_section(ui, "external_control_server", crate::i18n::tr("faber.external_control.server"), |ui| {
            ui.horizontal(|ui| {
                let response = ui_kit::checkbox(ui, crate::i18n::tr("faber.external_control.enable"), &mut app.preferences.agent_control)
                    .backing_on_hover_text(crate::i18n::tr("faber.external_control.enable_note"));
                scenario::publish_handle("prefs:agent_control", response.rect.center());
                ui_kit::help_icon(ui, crate::i18n::tr("faber.external_control.enable_note"));
            });

            let status = if app.external_control_available() && !app.preferences.agent_control {
                crate::i18n::tr("faber.external_control.stops_after_restart")
            } else if app.external_control_available() {
                crate::i18n::tr("faber.external_control.running")
            } else if app.preferences.agent_control {
                crate::i18n::tr("faber.external_control.restart")
            } else {
                crate::i18n::tr("faber.external_control.stopped")
            };
            ui_kit::text(ui, status, ui_kit::Text::Hint("external_control_status"));
        });

        ui_kit::settings_section(ui, "external_control_connect", crate::i18n::tr("faber.external_control.connect"), |ui| {
            ui_kit::text(ui, crate::i18n::tr("faber.external_control.connect_intro"), ui_kit::Text::Note("external_control_intro"));
            ui.horizontal_wrapped(|ui| {
                ui.monospace(MCP_COMMAND);
                let response = ui_kit::button(ui, crate::i18n::tr("ui.copy"), Button::Normal);
                scenario::publish_handle("prefs:external_control_copy", response.rect.center());
                if response.clicked() {
                    ui.ctx().copy_text(MCP_COMMAND.to_owned());
                    app.set_status(crate::i18n::tr("faber.external_control.copied"), false);
                }
            });
            ui_kit::text(ui, crate::i18n::tr("faber.external_control.local_note"), ui_kit::Text::Hint("external_control_local"));
        });

        ui_kit::settings_section(ui, "external_control_experience", crate::i18n::tr("faber.external_control.experience"), |ui| {
            ui.horizontal(|ui| {
                let response = ui_kit::checkbox(ui, crate::i18n::tr("faber.external_control.background"), &mut app.preferences.agent_off_thread)
                    .backing_on_hover_text(crate::i18n::tr("faber.external_control.background_note"));
                scenario::publish_handle("prefs:agent_off_thread", response.rect.center());
                ui_kit::help_icon(ui, crate::i18n::tr("faber.external_control.background_note"));
            });
            ui.horizontal(|ui| {
                let response = ui_kit::checkbox(ui, crate::i18n::tr("faber.external_control.compact"), &mut app.preferences.mcp_compact)
                    .backing_on_hover_text(crate::i18n::tr("faber.external_control.compact_note"));
                scenario::publish_handle("prefs:mcp_compact", response.rect.center());
                ui_kit::help_icon(ui, crate::i18n::tr("faber.external_control.compact_note"));
            });
            ui.horizontal(|ui| {
                let response = ui_kit::checkbox(ui, crate::i18n::tr("faber.external_control.pointer"), &mut app.ui.agent_cursor.show)
                    .backing_on_hover_text(crate::i18n::tr("faber.external_control.pointer_note"));
                scenario::publish_handle("prefs:external_pointer", response.rect.center());
                ui_kit::help_icon(ui, crate::i18n::tr("faber.external_control.pointer_note"));
            });
        });
    });
}
