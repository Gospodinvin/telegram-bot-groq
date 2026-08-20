# audio_processor.py
import logging
from faster_whisper import WhisperModel
import config

logger = logging.getLogger(__name__)


class AudioProcessor:
    def __init__(self):
        self.model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
            num_workers=config.WHISPER_NUM_WORKERS
        )
        logger.info(f"Whisper загружен на {config.WHISPER_DEVICE} с моделью {config.WHISPER_MODEL}")

    def transcribe(self, audio_path):
        try:
            segments, info = self.model.transcribe(
                audio_path,
                beam_size=5,
                language='ru',
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            full_text = ' '.join([seg.text for seg in segments])
            logger.info(f"Распознано {len(full_text)} символов")
            return full_text
        except Exception as e:
            logger.error(f"Ошибка распознавания: {e}", exc_info=True)
            return None