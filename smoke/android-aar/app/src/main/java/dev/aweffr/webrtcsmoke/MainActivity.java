package dev.aweffr.webrtcsmoke;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;
import java.util.Arrays;
import org.webrtc.CastTuningConfig;
import org.webrtc.CastTuningController;
import org.webrtc.CastTuningSnapshot;
import org.webrtc.DefaultVideoDecoderFactory;
import org.webrtc.PeerConnectionFactory;
import org.webrtc.VideoCodecInfo;

/** Runtime smoke for the app-consumable WebRTC AAR contract. */
public final class MainActivity extends Activity {
  private static final String TAG = "WebRTCAarSmoke";

  @Override
  protected void onCreate(Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    TextView result = new TextView(this);
    result.setText("AAR smoke running");
    setContentView(result);

    try {
      PeerConnectionFactory.initialize(
          PeerConnectionFactory.InitializationOptions.builder(this)
              .createInitializationOptions());
      PeerConnectionFactory factory =
          PeerConnectionFactory.builder().createPeerConnectionFactory();
      VideoCodecInfo[] codecs =
          new DefaultVideoDecoderFactory(null).getSupportedCodecs();
      boolean hasH264 =
          Arrays.stream(codecs)
              .anyMatch(codec -> "H264".equalsIgnoreCase(codec.name));
      if (!hasH264) {
        throw new IllegalStateException("H264 decoder capability is unavailable");
      }
      CastTuningConfig tuningConfig = CastTuningConfig.fromJson(
          "{\"schema_version\":2,\"profile\":\"DETAIL_IDLE\"}");
      try (CastTuningController controller = new CastTuningController(tuningConfig)) {
        CastTuningSnapshot snapshot = controller.snapshot();
        if (snapshot.sessionId == null || snapshot.sessionId.isEmpty()
            || snapshot.effectiveConfigHash == null
            || snapshot.effectiveConfigHash.isEmpty()) {
          throw new IllegalStateException("CastTuning native snapshot is empty");
        }
      }
      factory.dispose();
      result.setText("AAR_SMOKE_OK");
      Log.i(TAG, "AAR_SMOKE_OK codecs=" + Arrays.toString(codecs));
    } catch (Throwable failure) {
      result.setText("AAR_SMOKE_FAILED: " + failure.getClass().getSimpleName());
      Log.e(TAG, "AAR_SMOKE_FAILED", failure);
      throw new RuntimeException("WebRTC AAR runtime smoke failed", failure);
    }
  }
}
