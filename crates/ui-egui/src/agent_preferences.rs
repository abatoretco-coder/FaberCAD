//! Data-only compatibility for saved preferences from the former embedded assistant.
//!
//! These values are retained so old settings round-trip without loading a chat UI,
//! model client, process runner, provider catalogue or credential backend.

/// Saved turn limit: zero means unlimited (the current default).
pub const DEFAULT_TURN_LIMIT: u32 = 0;
/// Historical default interpreted as unlimited when loading old preferences.
pub const OLD_DEFAULT_TURN_LIMIT: u32 = 24;

use serde::{Deserialize, Serialize};

/// How much the agent may do without asking.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    /// Every change to the design, file and destructive action asks first.
    Ask,
    /// Modelling commands run; files and destructive actions still ask (the default).
    #[default]
    Edits,
    /// Nothing asks (crash reports and the folder limits still hold).
    All,
}

impl Mode {
    pub const ALL: [Mode; 3] = [Mode::Ask, Mode::Edits, Mode::All];
    pub fn id(self) -> &'static str {
        match self {
            Mode::Ask => "ask",
            Mode::Edits => "edits",
            Mode::All => "all",
        }
    }
    pub fn parse(s: &str) -> Option<Mode> {
        Mode::ALL.into_iter().find(|m| m.id() == s)
    }
    pub fn label(self) -> &'static str {
        crate::i18n::tr(match self {
            Mode::Ask => "ui.ai_mode_ask",
            Mode::Edits => "ui.ai_mode_edits",
            Mode::All => "ui.ai_mode_all",
        })
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    /// A program that speaks the Agent Client Protocol.
    #[default]
    Acp,
    /// An OpenAI-compatible chat completions endpoint.
    Api,
    /// An Anthropic-compatible Messages endpoint.
    Anthropic,
}

impl Kind {
    /// The id written in preferences and on the control channel.
    pub fn id(self) -> &'static str {
        match self {
            Kind::Acp => "acp",
            Kind::Api => "api",
            Kind::Anthropic => "anthropic",
        }
    }
    /// Whether the agent is an endpoint SolidCraft talks to itself (either protocol).
    pub fn is_api(self) -> bool {
        matches!(self, Kind::Api | Kind::Anthropic)
    }
    /// The wire protocol of an added endpoint; `None` for an ACP agent.
    pub fn protocol(self) -> Option<Protocol> {
        match self {
            Kind::Acp => None,
            Kind::Api => Some(Protocol::OpenAi),
            Kind::Anthropic => Some(Protocol::Anthropic),
        }
    }
}

/// The wire protocol of an endpoint the user added.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub enum Protocol {
    /// `{base}/chat/completions`, as Ollama, LM Studio, OpenAI and their kin speak.
    #[default]
    OpenAi,
    /// `{base}/v1/messages`, as the Anthropic Messages API and compatible endpoints speak.
    Anthropic,
}

impl Protocol {
    pub fn kind(self) -> Kind {
        match self {
            Protocol::OpenAi => Kind::Api,
            Protocol::Anthropic => Kind::Anthropic,
        }
    }
}

/// An agent the user added.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct AgentConfig {
    pub id: String,
    pub name: String,
    pub kind: Kind,
    /// ACP: the command line.
    pub command: String,
    /// API: the endpoint (`…/v1`) and model.
    pub base_url: String,
    pub model: String,
    /// Added with the Ollama preset (even if its display name changes).
    pub ollama: bool,
    /// API: a key is stored for it in the system keychain.
    pub key: bool,
    /// OpenAI-compatible API: explicit consent to send the key over HTTP to this endpoint.
    pub allow_insecure_http: bool,
    /// API: how long one model request may take, in seconds (clamped to
    /// [`MIN_REQUEST_TIMEOUT_S`]..=[`MAX_REQUEST_TIMEOUT_S`] where it is used).
    pub request_timeout_s: u64,
    /// API: the reasoning effort to send as `reasoning_effort`; empty sends nothing and the
    /// provider's own default applies (trimmed and length-capped by [`reasoning_effort`]).
    pub reasoning_effort: String,
}

impl Default for AgentConfig {
    fn default() -> AgentConfig {
        AgentConfig {
            id: String::new(),
            name: String::new(),
            kind: Kind::default(),
            command: String::new(),
            base_url: String::new(),
            model: String::new(),
            ollama: false,
            key: false,
            allow_insecure_http: false,
            request_timeout_s: DEFAULT_REQUEST_TIMEOUT_S,
            reasoning_effort: String::new(),
        }
    }
}

/// How long one model request to an endpoint may take by default, in seconds.
pub const DEFAULT_REQUEST_TIMEOUT_S: u64 = 300;
/// The shortest request timeout an endpoint can have.
pub const MIN_REQUEST_TIMEOUT_S: u64 = 30;
/// The longest request timeout an endpoint can have (an hour).
pub const MAX_REQUEST_TIMEOUT_S: u64 = 3600;

/// A request timeout in range: seconds from a preferences file, the dialog or the control
/// channel, rounded and clamped; anything not a finite number is the default.
pub fn request_timeout_s(secs: f64) -> u64 {
    if !secs.is_finite() {
        return DEFAULT_REQUEST_TIMEOUT_S;
    }
    // Clamped first, so the cast is exact.
    secs.round().clamp(MIN_REQUEST_TIMEOUT_S as f64, MAX_REQUEST_TIMEOUT_S as f64) as u64
}

/// The longest reasoning effort an endpoint can be given (no provider names one near this).
pub const MAX_REASONING_EFFORT_LEN: usize = 64;

/// A reasoning effort as stored: trimmed, and capped so a hand-edited preferences file or the
/// control channel cannot carry an absurd value into every request. Empty means "send nothing".
pub fn reasoning_effort(raw: &str) -> String {
    raw.trim().chars().take(MAX_REASONING_EFFORT_LEN).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn old_saved_configuration_preserves_all_serialized_fields() {
        let saved = json!({"id":"old-local","name":"Local model","kind":"api","command":"",
            "base_url":"http://127.0.0.1:11434/v1","model":"saved-model","ollama":true,
            "key":true,"allow_insecure_http":true,"request_timeout_s":90,"reasoning_effort":"low"});
        let loaded: AgentConfig = serde_json::from_value(saved.clone()).unwrap();
        assert_eq!(serde_json::to_value(loaded).unwrap(), saved);
        for mode in ["ask", "edits", "all"] {
            let loaded: Mode = serde_json::from_value(json!(mode)).unwrap();
            assert_eq!(serde_json::to_value(loaded).unwrap(), json!(mode));
        }
    }

    #[test]
    fn missing_legacy_fields_keep_the_original_defaults() {
        let config: AgentConfig = serde_json::from_value(json!({"id":"old-command"})).unwrap();
        assert_eq!(config.kind, Kind::Acp);
        assert_eq!(config.request_timeout_s, 300);
        assert!(!config.key);
        assert!(!config.allow_insecure_http);
        assert_eq!(Mode::default(), Mode::Edits);
        assert_eq!(DEFAULT_TURN_LIMIT, 0);
        assert_eq!(OLD_DEFAULT_TURN_LIMIT, 24);
    }
}
