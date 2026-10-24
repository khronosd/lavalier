"""Builders for synthetic pendant messages (copied from the decoder library's tests)."""

from pendant_client.proto import flash_page_pb2, server_pb2


def make_storage_buffer_msg(*, page_index: int, flash_page: bytes,
                            ingest_type: int = 2,
                            session: int = 0,
                            run: int = 0,
                            seq: int = 0) -> bytes:
    """Build one PendantAllMsg with a StorageBufferMsg in it."""
    msg = server_pb2.PendantAllMsg()
    msg.storage_buffer.ingest_type = ingest_type
    msg.storage_buffer.session = session
    msg.storage_buffer.run = run
    msg.storage_buffer.seq = seq
    msg.storage_buffer.index = page_index
    msg.storage_buffer.flash_page = flash_page
    return msg.SerializeToString()


def make_audio_flash_page(opus_bytes: bytes,
                          did_start_recording: bool = False,
                          did_stop_recording: bool = False,
                          absolute_timestamp_ms: int = 0) -> bytes:
    page = flash_page_pb2.FlashPage()
    page.absolute_timestamp_ms = absolute_timestamp_ms
    c = page.chunks.add()
    c.audio_data.codec_beamforming_data = opus_bytes
    c.audio_data.did_start_recording = did_start_recording
    c.audio_data.did_stop_recording = did_stop_recording
    return page.SerializeToString()


def make_storage_session_stop_page() -> bytes:
    page = flash_page_pb2.FlashPage()
    c = page.chunks.add()
    c.storage_status.did_stop_storage_session = True
    return page.SerializeToString()


def make_button_page(ts_ms: int, absolute_timestamp_ms: int = 0) -> bytes:
    page = flash_page_pb2.FlashPage()
    page.absolute_timestamp_ms = absolute_timestamp_ms
    c = page.chunks.add()
    c.button_status.button_event = 1
    c.button_status.button_event_absolute_timestamp_ms = ts_ms
    return page.SerializeToString()
