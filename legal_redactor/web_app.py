"""Backward-compatible Web UI entrypoint.

Implementation lives in ``legal_redactor.web.*``. This module re-exports the
FastAPI ``app`` and helpers so existing imports keep working:

    from legal_redactor.web_app import app
"""
from __future__ import annotations

import http
import subprocess
import urllib

from .web.app import app, register_routes
from .web import deps as _deps
from .web_templates import _page
from .cases import (
    case_location_search_roots,
    suggest_case_location_from_filenames,
    persist_case_redaction,
)

# Patchable dependencies — prefer ``legal_redactor.web.deps.*`` in new tests.
RedactionPipeline = _deps.RedactionPipeline
probe_model_manager = _deps.probe_model_manager
build_status_payload = _deps.build_status_payload
load_json_config = _deps.load_json_config
config_value = _deps.config_value
RecognitionUnavailableError = _deps.RecognitionUnavailableError
PipelineConfig = _deps.PipelineConfig
DEFAULT_MODEL_ID = _deps.DEFAULT_MODEL_ID

from .web.models import (
    SAMPLE_SUMMARY_KEYS,
    SUPPORTED_UPLOAD_SUFFIXES,
    RECOGNITION_MODE_LABELS,
    RECOGNITION_STATUS_LABELS,
    InputDocument,
    DiscordApiError,
)

from .web.status_ops import (
    _render_status_panel,
    health,
    api_status,
    api_models,
    api_model_status,
    _model_manager_json,
    _available_model_options,
    _pipeline_config_for_model_status,
    _status_payload,
)

from .web.workflow import (
    _redaction_failure_body,
    _reject_forged_workflow_fields,
    _reject_forged_workflow_form_data,
    _case_error_response,
    _waiting_hermes_response,
    _render_case_workflow_panel,
    _workflow_state_label,
    _should_apply_auto_prefill,
    _persist_optional_case_redaction,
    _apply_requested_thread_preflight,
    _safe_public_error_message,
    _case_manifest_fields,
)

from .web.documents import (
    _excel_source,
    _render_output_document,
    _excel_warnings,
    _read_input_documents,
    _decode_text_bytes,
    _suffix_for_filename,
    _is_supported_folder_upload_filename,
    _docx_bytes_to_text,
    _legacy_doc_bytes_to_text,
    _read_restore_map_text,
    _read_upload_text_from_bytes,
    _read_upload_text,
    _form_list_value,
    _data_download,
    _binary_download,
    _documents_bundle_json,
    _documents_from_bundle_json,
    _apply_map_to_documents,
)

from .web.discord_ops import (
    send_redacted_to_discord,
    create_discord_thread,
    bind_discord_thread,
    attach_to_bound_discord_thread,
    _discord_create_thread_section,
    _discord_send_section,
    _discord_bot_token,
    _new_discord_request_id,
    _case_creation_command,
    _safe_discord_request_id,
    _case_creation_title,
    _clean_case_cause,
    _find_discord_thread_for_case,
    _get_discord_json,
    _contains_local_path_text,
    _discord_command_channel_id,
    _post_discord_channel_message,
    _post_discord_thread_file,
    _safe_discord_attachment_message,
    _multipart_form_data,
)

from .web.case_location import (
    suggest_case_location,
    _is_default_case_root_value,
    _resolve_case_location,
    _find_case_directories,
    _suggest_case_location_from_relative_paths,
    _safe_upload_relative_paths,
    _case_folder_from_relative_paths,
    _case_folder_hint_summary,
)

from .web.mapping_ops import (
    _ORG_ALIAS_SUFFIXES,
    _entity_group_is_noise,
    _sanitize_redaction_map,
    suggest_mapping_entry,
    _source_indicates_manual,
    _source_indicates_sample,
    _review_candidate_text_set,
    _classify_mapping_review_row,
    _restore_risk_reasons,
    _render_mapping_review_toolbar,
    _render_category_badges,
    _review_candidate_texts_json,
    _render_mapping_edit_rows,
    _render_mapping_edit_row,
    _render_blank_mapping_row,
    _redaction_map_from_rows,
    _find_mapping_by_original,
    _organization_originals_are_aliases,
    _mapping_entries_share_entity,
    _mapping_entity_group_ids,
    _renumber_mapping_placeholders,
    _next_group_ordinal,
    _renumber_counter_key,
    _person_mask_stem,
    _mask_with_group_ordinal,
    _mask_with_ordinal_prefix,
    _project_suffix,
    _suggest_manual_mapping_entry,
    _suggest_manual_mask,
    _next_person_ordinal,
    _next_mask_ordinal,
    _ordinal_index,
    _ordinal_value,
    _manual_organization_suffix,
    _manual_location_suffix,
    _highlight_replaced_text,
    _guess_location_mask,
    _simple_mask,
)

from .web.samples_ops import (
    _sample_entry_original,
    _sample_entry_core,
    _sample_effective_delta,
    _load_sample_entries_for_delta,
    _summary_item_from_entry,
    _empty_sample_summary,
    _sample_provenance,
    _build_sample_save_summary,
    _sample_summary_response,
    save_sample_page,
    _diagnose_sample_entry,
    edit_samples_page,
    update_sample_entry,
    add_sample_entry,
    delete_sample_entry,
    compact_samples_page,
    clear_samples_page,
    api_clear_samples,
    _render_sample_summary_panel,
)

from .web.restore_ops import (
    restore_preview_page,
    _render_docx_restore_result,
)

from .web.redact_routes import (
    index,
    analyze_page,
    _render_audit_dashboard,
    redact_confirmed_page,
    redact_page,
    apply_map_page,
    apply_edited_map_page,
    _recognition_stats_from_analysis,
    _recognition_reason_label,
    _render_recognition_stats,
    _render_redaction_result,
    _render_batch_redaction_result,
)

__all__ = ['app', 'register_routes', 'RedactionPipeline', 'probe_model_manager', 'build_status_payload', 'load_json_config', 'config_value', 'RecognitionUnavailableError', 'PipelineConfig', 'DEFAULT_MODEL_ID', 'subprocess', 'http', 'urllib', '_page', 'case_location_search_roots', 'suggest_case_location_from_filenames', 'persist_case_redaction', 'SAMPLE_SUMMARY_KEYS', 'SUPPORTED_UPLOAD_SUFFIXES', 'RECOGNITION_MODE_LABELS', 'RECOGNITION_STATUS_LABELS', 'InputDocument', 'DiscordApiError', '_render_status_panel', 'health', 'api_status', 'api_models', 'api_model_status', '_model_manager_json', '_available_model_options', '_pipeline_config_for_model_status', '_status_payload', '_redaction_failure_body', '_reject_forged_workflow_fields', '_reject_forged_workflow_form_data', '_case_error_response', '_waiting_hermes_response', '_render_case_workflow_panel', '_workflow_state_label', '_should_apply_auto_prefill', '_persist_optional_case_redaction', '_apply_requested_thread_preflight', '_safe_public_error_message', '_case_manifest_fields', '_excel_source', '_render_output_document', '_excel_warnings', '_read_input_documents', '_decode_text_bytes', '_suffix_for_filename', '_is_supported_folder_upload_filename', '_docx_bytes_to_text', '_legacy_doc_bytes_to_text', '_read_restore_map_text', '_read_upload_text_from_bytes', '_read_upload_text', '_form_list_value', '_data_download', '_binary_download', '_documents_bundle_json', '_documents_from_bundle_json', '_apply_map_to_documents', 'send_redacted_to_discord', 'create_discord_thread', 'bind_discord_thread', 'attach_to_bound_discord_thread', '_discord_create_thread_section', '_discord_send_section', '_discord_bot_token', '_new_discord_request_id', '_case_creation_command', '_safe_discord_request_id', '_case_creation_title', '_clean_case_cause', '_find_discord_thread_for_case', '_get_discord_json', '_contains_local_path_text', '_discord_command_channel_id', '_post_discord_channel_message', '_post_discord_thread_file', '_safe_discord_attachment_message', '_multipart_form_data', 'suggest_case_location', '_is_default_case_root_value', '_resolve_case_location', '_find_case_directories', '_suggest_case_location_from_relative_paths', '_safe_upload_relative_paths', '_case_folder_from_relative_paths', '_case_folder_hint_summary', '_ORG_ALIAS_SUFFIXES', '_entity_group_is_noise', '_sanitize_redaction_map', 'suggest_mapping_entry', '_source_indicates_manual', '_source_indicates_sample', '_review_candidate_text_set', '_classify_mapping_review_row', '_restore_risk_reasons', '_render_mapping_review_toolbar', '_render_category_badges', '_review_candidate_texts_json', '_render_mapping_edit_rows', '_render_mapping_edit_row', '_render_blank_mapping_row', '_redaction_map_from_rows', '_find_mapping_by_original', '_organization_originals_are_aliases', '_mapping_entries_share_entity', '_mapping_entity_group_ids', '_renumber_mapping_placeholders', '_next_group_ordinal', '_renumber_counter_key', '_person_mask_stem', '_mask_with_group_ordinal', '_mask_with_ordinal_prefix', '_project_suffix', '_suggest_manual_mapping_entry', '_suggest_manual_mask', '_next_person_ordinal', '_next_mask_ordinal', '_ordinal_index', '_ordinal_value', '_manual_organization_suffix', '_manual_location_suffix', '_highlight_replaced_text', '_guess_location_mask', '_simple_mask', '_sample_entry_original', '_sample_entry_core', '_sample_effective_delta', '_load_sample_entries_for_delta', '_summary_item_from_entry', '_empty_sample_summary', '_sample_provenance', '_build_sample_save_summary', '_sample_summary_response', 'save_sample_page', '_diagnose_sample_entry', 'edit_samples_page', 'update_sample_entry', 'add_sample_entry', 'delete_sample_entry', 'compact_samples_page', 'clear_samples_page', 'api_clear_samples', '_render_sample_summary_panel', 'restore_preview_page', '_render_docx_restore_result', 'index', 'analyze_page', '_render_audit_dashboard', 'redact_confirmed_page', 'redact_page', 'apply_map_page', 'apply_edited_map_page', '_recognition_stats_from_analysis', '_recognition_reason_label', '_render_recognition_stats', '_render_redaction_result', '_render_batch_redaction_result']
