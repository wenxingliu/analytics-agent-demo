"""Streamlit UI: chat, SQL viewer, results table and model picker."""

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent)
)  # `streamlit run` doesn't add the repo root

import streamlit as st

from analytics_agent import agent, db, llm
from analytics_agent.agent import Conversation, Reply
from analytics_agent.config import ConfigError, Provider, load_providers, settings
from analytics_agent.metadata import Metadata, MetadataError, load_metadata


@st.cache_resource
def get_metadata() -> Metadata:
    return load_metadata(settings.semantic_layer_path)


@st.cache_data(ttl=600, show_spinner=False)
def cached_models(provider: Provider) -> list[str]:
    return llm.list_models(provider)


def pick_model(providers: dict[str, Provider]) -> Provider:
    """Provider and model selectors; models come from the provider's API."""
    name = st.selectbox("Provider", list(providers), format_func=lambda n: providers[n].label)
    provider = providers[name]
    models = cached_models(provider)
    if not models:
        st.caption("Could not list models; type a model id.")
        model = st.text_input("Model", provider.model, key=f"model-{name}")
        return replace(provider, model=model)
    if provider.model and provider.model not in models:
        models = [provider.model, *models]
    default = models.index(provider.model) if provider.model in models else 0
    model = st.selectbox("Model", models, index=default, key=f"model-{name}")
    return replace(provider, model=model)


def render_sidebar(providers: dict[str, Provider]) -> Provider:
    """Draw the sidebar and return the provider and model the user picked."""
    with st.sidebar:
        provider = pick_model(providers)
        if st.button("New conversation", width="stretch"):
            st.session_state.conversation = Conversation()
            st.rerun()
        st.caption(f"Database: {db.get_engine().url.render_as_string(hide_password=True)}")
    return provider


def render_reply(reply: Reply, key: str, is_last: bool) -> None:
    if reply.text:
        st.markdown(reply.text)
    if reply.error:
        st.error(reply.error)
    if reply.question:
        st.markdown(reply.question)
        if is_last:
            for i, option in enumerate(reply.options):
                if st.button(option, key=f"{key}-option-{i}"):
                    st.session_state.pending = option
                    st.rerun()
    if reply.sql:
        with st.expander("SQL", expanded=bool(reply.error)):
            st.code(db.format_sql(reply.sql), language="sql")
    if reply.dataframe is not None:
        st.dataframe(reply.dataframe, width="stretch")
        st.caption(f"{len(reply.dataframe)} rows")
        st.download_button(
            "Download CSV",
            reply.dataframe.to_csv(index=False),
            "results.csv",
            "text/csv",
            key=f"{key}-csv",
        )


def render_starters(metadata: Metadata) -> None:
    questions = metadata.knowledge.app.starter_questions or [
        e.question for e in metadata.examples[:3]
    ]
    for i, question in enumerate(questions):
        if st.button(question, key=f"starter-{i}"):
            st.session_state.pending = question
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="Analytics Agent", layout="wide")
    try:
        providers = load_providers()
        metadata = get_metadata()
    except (ConfigError, MetadataError) as e:
        st.error(str(e))
        st.stop()

    st.title(metadata.knowledge.app.title)
    st.caption(metadata.knowledge.app.subtitle)
    provider = render_sidebar(providers)

    if "conversation" not in st.session_state:
        st.session_state.conversation = Conversation()
    conversation: Conversation = st.session_state.conversation

    if not conversation.turns:
        render_starters(metadata)
    for i, (role, content) in enumerate(conversation.turns):
        with st.chat_message(role):
            if isinstance(content, Reply):
                render_reply(content, f"turn-{i}", is_last=i == len(conversation.turns) - 1)
            else:
                st.markdown(content)

    message = st.session_state.pop("pending", None) or st.chat_input("Ask a question")
    if message:
        with st.chat_message("user"):
            st.markdown(message)
        with st.spinner("Thinking..."):
            agent.answer(metadata, conversation, message, provider)
        st.rerun()


main()
