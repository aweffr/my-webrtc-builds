#include "api/cast_tuning/cast_tuning_telemetry.h"

#include <iomanip>
#include <sstream>
#include <utility>

namespace webrtc::cast_tuning {
namespace {

std::string JsonString(const std::string& value) {
  std::ostringstream escaped;
  escaped << '"';
  for (unsigned char character : value) {
    switch (character) {
      case '"':
        escaped << "\\\"";
        break;
      case '\\':
        escaped << "\\\\";
        break;
      case '\b':
        escaped << "\\b";
        break;
      case '\f':
        escaped << "\\f";
        break;
      case '\n':
        escaped << "\\n";
        break;
      case '\r':
        escaped << "\\r";
        break;
      case '\t':
        escaped << "\\t";
        break;
      default:
        if (character < 0x20) {
          escaped << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                  << static_cast<int>(character) << std::dec;
        } else {
          escaped << character;
        }
    }
  }
  escaped << '"';
  return escaped.str();
}

bool LooksLikeJsonValue(const std::string& value) {
  if (value.empty())
    return false;
  const char first = value.front();
  return first == '{' || first == '[' || first == '"' || first == '-' ||
         (first >= '0' && first <= '9') || value == "true" ||
         value == "false" || value == "null";
}

}  // namespace

CastTelemetryWriter::CastTelemetryWriter(std::string path)
    : output_(std::move(path), std::ios::out | std::ios::app),
      writer_thread_(&CastTelemetryWriter::Run, this) {}

CastTelemetryWriter::~CastTelemetryWriter() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    stopping_ = true;
  }
  work_available_.notify_one();
  writer_thread_.join();
}

void CastTelemetryWriter::Emit(CastTelemetryEvent event) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (stopping_)
      return;
    queue_.push_back(std::move(event));
  }
  work_available_.notify_one();
}

void CastTelemetryWriter::Flush() {
  std::unique_lock<std::mutex> lock(mutex_);
  drained_.wait(lock, [this] { return queue_.empty() && !writing_; });
}

uint64_t CastTelemetryWriter::write_failures() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return write_failures_;
}

void CastTelemetryWriter::Run() {
  while (true) {
    CastTelemetryEvent event;
    {
      std::unique_lock<std::mutex> lock(mutex_);
      work_available_.wait(lock,
                           [this] { return stopping_ || !queue_.empty(); });
      if (queue_.empty() && stopping_)
        break;
      event = std::move(queue_.front());
      queue_.pop_front();
      writing_ = true;
    }

    output_ << Serialize(event) << '\n';
    output_.flush();

    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (!output_)
        ++write_failures_;
      writing_ = false;
      if (queue_.empty())
        drained_.notify_all();
    }
  }
  std::lock_guard<std::mutex> lock(mutex_);
  writing_ = false;
  drained_.notify_all();
}

std::string CastTelemetryWriter::Serialize(const CastTelemetryEvent& event) {
  std::ostringstream json;
  json << "{\"schema_version\":1,\"event_type\":"
       << JsonString(event.event_type)
       << ",\"timestamp_ms\":" << event.timestamp_ms
       << ",\"session_id\":" << JsonString(event.session_id)
       << ",\"config_hash\":" << JsonString(event.config_hash)
       << ",\"revision\":" << event.revision << ",\"payload\":"
       << (LooksLikeJsonValue(event.payload_json) ? event.payload_json : "null")
       << '}';
  return json.str();
}

}  // namespace webrtc::cast_tuning
