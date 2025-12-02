"""Test script to verify debug logging configuration."""
import os
import logging

# Set debug mode
os.environ["NEUROGLANCER_CHAT_DEBUG"] = "1"

# Enable verbose debug logging when NEUROGLANCER_CHAT_DEBUG is set (1/true/yes)
DEBUG_ENABLED = os.getenv("NEUROGLANCER_CHAT_DEBUG", "").lower() in ("1", "true", "yes")

# Configure logging level based on debug flag
log_level = logging.DEBUG if DEBUG_ENABLED else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True  # Force reconfiguration even if logging was already configured
)

# Also configure uvicorn's loggers to respect our debug level
if DEBUG_ENABLED:
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        logging.getLogger(logger_name).setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)

# Test all log levels
print("\n" + "="*60)
print("TESTING LOGGING CONFIGURATION")
print("="*60)
print(f"DEBUG_ENABLED: {DEBUG_ENABLED}")
print(f"Configured log level: {logging.getLevelName(log_level)}")
print(f"Root logger level: {logging.getLevelName(logging.getLogger().level)}")
print(f"Test logger level: {logging.getLevelName(logger.level)}")
print("="*60 + "\n")

# Log debug mode status
if DEBUG_ENABLED:
    logger.warning("\ud83d\udd0d DEBUG MODE ENABLED - Verbose logging active (NEUROGLANCER_CHAT_DEBUG=1)")
else:
    logger.info("Debug mode disabled.")

# Test different log levels
logger.debug("✅ This is a DEBUG message - you should see this!")
logger.info("ℹ️  This is an INFO message - you should see this!")
logger.warning("⚠️  This is a WARNING message - you should see this!")
logger.error("❌ This is an ERROR message - you should see this!")

print("\n" + "="*60)
print("If you see all 4 messages above (DEBUG, INFO, WARNING, ERROR)")
print("then logging is working correctly!")
print("="*60 + "\n")
