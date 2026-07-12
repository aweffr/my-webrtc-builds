#ifndef API_CAST_TUNING_CAST_TUNING_TELEMETRY_H_
#define API_CAST_TUNING_CAST_TUNING_TELEMETRY_H_

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>

namespace webrtc::cast_tuning {

struct CastTelemetryEvent {
  std::string event_type;
  int64_t timestamp_ms = 0;
  std::string session_id;
  std::string config_hash;
  uint64_t revision = 0;
  // Must be one complete JSON value. Invalid values are written as null.
  std::string payload_json = "{}";
};

// A non-media-thread JSONL sink. Emit only enqueues; disk I/O is performed by
// the writer thread. Flush is intended for shutdown and tests, not media paths.
class CastTelemetryWriter {
 public:
  explicit CastTelemetryWriter(std::string path);
  ~CastTelemetryWriter();

  CastTelemetryWriter(const CastTelemetryWriter&) = delete;
  CastTelemetryWriter& operator=(const CastTelemetryWriter&) = delete;

  void Emit(CastTelemetryEvent event);
  void Flush();
  uint64_t write_failures() const;

 private:
  void Run();
  static std::string Serialize(const CastTelemetryEvent& event);

  mutable std::mutex mutex_;
  std::condition_variable work_available_;
  std::condition_variable drained_;
  std::deque<CastTelemetryEvent> queue_;
  std::ofstream output_;
  std::thread writer_thread_;
  uint64_t write_failures_ = 0;
  bool writing_ = false;
  bool stopping_ = false;
};

}  // namespace webrtc::cast_tuning

#endif  // API_CAST_TUNING_CAST_TUNING_TELEMETRY_H_
