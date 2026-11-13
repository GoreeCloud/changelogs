package com.goreecloud.changelogs;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Native, read-only viewer for the owner's loopback changelog API.
 * No token persistence, analytics, WebView, or third-party runtime libraries.
 */
public final class MainActivity extends Activity {
    private static final String API = "http://127.0.0.1:8765";
    private static final int MAX_BODY_BYTES = 512 * 1024;
    private static final int BACKGROUND = Color.rgb(9, 13, 26);
    private static final int PANEL = Color.rgb(24, 32, 52);
    private static final int TEXT = Color.rgb(242, 246, 255);
    private static final int MUTED = Color.rgb(176, 191, 221);
    private static final int ACCENT = Color.rgb(166, 196, 255);

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private EditText tokenInput;
    private EditText productInput;
    private EditText queryInput;
    private LinearLayout entries;
    private TextView status;
    private Button refresh;
    private Button loadMore;
    private String bearerToken = "";
    // Generations prevent responses in flight from repopulating cleared sessions.
    private long sessionVersion = 0;
    private long requestVersion = 0;
    private int offset = 0;
    private boolean hasMore = false;

    private int dp(float value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private GradientDrawable panel(int color) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(18));
        drawable.setStroke(dp(1), Color.rgb(60, 78, 108));
        return drawable;
    }

    private TextView text(String value, int size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setTypeface(Typeface.DEFAULT, bold ? Typeface.BOLD : Typeface.NORMAL);
        return view;
    }

    private EditText field(String hint, boolean password) {
        EditText value = new EditText(this);
        value.setSingleLine(true);
        value.setHint(hint);
        value.setHintTextColor(MUTED);
        value.setTextColor(TEXT);
        value.setTextSize(15);
        value.setPadding(dp(12), dp(12), dp(12), dp(12));
        value.setBackground(panel(Color.rgb(15, 21, 38)));
        value.setInputType(password
                ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
                : InputType.TYPE_CLASS_TEXT);
        return value;
    }

    private void addWithMargin(LinearLayout parent, View child, int top) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(top);
        parent.addView(child, params);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(BACKGROUND);
        getWindow().setNavigationBarColor(BACKGROUND);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BACKGROUND);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(26), dp(20), dp(28));
        scroll.addView(root);
        setContentView(scroll);

        if (Build.VERSION.SDK_INT >= 30) {
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                android.graphics.Insets system = insets.getInsets(WindowInsets.Type.systemBars());
                view.setPadding(dp(20), dp(26) + system.top, dp(20), dp(28) + system.bottom);
                return insets;
            });
        } else {
            root.setFitsSystemWindows(true);
        }

        TextView brand = text("◈  GoreeCloud", 16, ACCENT, true);
        addWithMargin(root, brand, 0);
        TextView title = text("Changelogs", 34, TEXT, true);
        addWithMargin(root, title, 25);
        TextView subtitle = text("Your changes, documented. Private local-first release history.", 15, MUTED, false);
        addWithMargin(root, subtitle, 6);

        LinearLayout connection = new LinearLayout(this);
        connection.setOrientation(LinearLayout.VERTICAL);
        connection.setPadding(dp(18), dp(18), dp(18), dp(18));
        connection.setBackground(panel(PANEL));
        addWithMargin(root, connection, 28);

        connection.addView(text("LOCAL API · READ ONLY", 12, ACCENT, true));
        tokenInput = field("Paste bearer token (32+ characters)", true);
        tokenInput.setSaveEnabled(false);
        tokenInput.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        addWithMargin(connection, tokenInput, 12);
        productInput = field("Filter by product (optional)", false);
        addWithMargin(connection, productInput, 10);
        queryInput = field("Search history (optional)", false);
        addWithMargin(connection, queryInput, 10);

        refresh = new Button(this);
        refresh.setText("Connect / Refresh");
        refresh.setAllCaps(false);
        refresh.setTextColor(BACKGROUND);
        refresh.setBackgroundTintList(android.content.res.ColorStateList.valueOf(ACCENT));
        addWithMargin(connection, refresh, 14);
        refresh.setOnClickListener(v -> load());

        Button disconnect = new Button(this);
        disconnect.setText("Clear session");
        disconnect.setAllCaps(false);
        disconnect.setTextColor(TEXT);
        addWithMargin(connection, disconnect, 5);
        disconnect.setOnClickListener(v -> {
            ++sessionVersion;
            ++requestVersion;
            bearerToken = "";
            offset = 0;
            hasMore = false;
            tokenInput.setText("");
            entries.removeAllViews();
            refresh.setEnabled(true);
            loadMore.setVisibility(View.GONE);
            setStatus("Session cleared. Earlier responses will be ignored.");
        });

        status = text("Use adb reverse tcp:8765 tcp:8765 to reach the host API.", 13, MUTED, false);
        status.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);
        addWithMargin(root, status, 18);

        entries = new LinearLayout(this);
        entries.setOrientation(LinearLayout.VERTICAL);
        addWithMargin(root, entries, 20);

        loadMore = new Button(this);
        loadMore.setText("Load more");
        loadMore.setAllCaps(false);
        loadMore.setTextColor(TEXT);
        loadMore.setVisibility(View.GONE);
        addWithMargin(root, loadMore, 18);
        loadMore.setOnClickListener(v -> loadNext());
    }

    private void setStatus(String value) {
        status.setText(value);
    }

    private String encode(String value) throws Exception {
        return URLEncoder.encode(value, StandardCharsets.UTF_8.name());
    }

    private void load() {
        requestPage(false);
    }

    private void loadNext() {
        if (hasMore) requestPage(true);
    }

    private void requestPage(boolean append) {
        String entered = tokenInput.getText().toString();
        if (!entered.isEmpty()) {
            ++sessionVersion;
            bearerToken = entered;
            tokenInput.setText("");
            offset = 0;
            hasMore = false;
        }
        if (bearerToken.length() < 32) {
            setStatus("A bearer token of at least 32 characters is required.");
            return;
        }
        if (append && !hasMore) return;
        final long startSession = sessionVersion;
        final long startRequest = ++requestVersion;
        final String suppliedToken = bearerToken;
        final String product = productInput.getText().toString().trim();
        final String query = queryInput.getText().toString().trim();
        final int requestedOffset = append ? offset : 0;
        refresh.setEnabled(false);
        loadMore.setEnabled(false);
        setStatus(append ? "Loading more changes…" : "Loading local changes…");
        executor.execute(() -> {
            try {
                String path = query.isEmpty()
                        ? "/v1/entries?limit=40&offset=" + requestedOffset
                        : "/v1/search?limit=40&offset=" + requestedOffset + "&q=" + encode(query);
                if (!product.isEmpty()) path += "&product=" + encode(product);
                JSONObject response = read(suppliedToken, path);
                JSONArray rows = response.getJSONArray("entries");
                final boolean nextPage = response.optBoolean("has_more", false) &&
                        rows.length() > 0 && requestedOffset + rows.length() <= 1000000;
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed() ||
                            startSession != sessionVersion || startRequest != requestVersion) return;
                    render(rows, append);
                    offset = requestedOffset + rows.length();
                    hasMore = nextPage;
                    loadMore.setVisibility(hasMore ? View.VISIBLE : View.GONE);
                    loadMore.setEnabled(hasMore);
                    refresh.setEnabled(true);
                    setStatus(rows.length() + " changes loaded" +
                            (append ? " on this page." : ".") + " Read only.");
                });
            } catch (Exception error) {
                // Never print a token, private query, or response body to logs or UI.
                final String message = error.getMessage() == null ? "Request failed" : error.getMessage();
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed() ||
                            startSession != sessionVersion || startRequest != requestVersion) return;
                    refresh.setEnabled(true);
                    loadMore.setEnabled(hasMore);
                    setStatus(message);
                });
            }
        });
    }

    private JSONObject read(String token, String path) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(API + path).openConnection();
        connection.setRequestMethod("GET");
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setConnectTimeout(4000);
        connection.setReadTimeout(7000);
        connection.setUseCaches(false);
        try {
            int response = connection.getResponseCode();
            if (response == 401) throw new IllegalStateException("Unauthorized: check your local token.");
            if (response != 200) throw new IllegalStateException("API response: HTTP " + response);
            try (InputStream stream = connection.getInputStream();
                 ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[4096];
                int count;
                while ((count = stream.read(buffer)) != -1) {
                    if (bytes.size() + count > MAX_BODY_BYTES)
                        throw new IllegalStateException("Response too large; refine filters.");
                    bytes.write(buffer, 0, count);
                }
                return new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
            }
        } finally {
            connection.disconnect();
        }
    }

    private void render(JSONArray rows, boolean append) {
        if (!append) entries.removeAllViews();
        if (rows.length() == 0 && !append) {
            addWithMargin(entries, text("No matching changes.", 15, MUTED, false), 10);
            return;
        }
        for (int index = 0; index < rows.length(); index++) {
            JSONObject item = rows.optJSONObject(index);
            if (item == null) continue;
            LinearLayout card = new LinearLayout(this);
            card.setOrientation(LinearLayout.VERTICAL);
            card.setPadding(dp(18), dp(18), dp(18), dp(18));
            card.setBackground(panel(PANEL));
            addWithMargin(entries, card, 12);

            String kind = item.optString("kind", "change").toUpperCase(java.util.Locale.ROOT);
            String date = item.optString("released_at", "");
            card.addView(text(kind + "  ·  " + date, 12, ACCENT, true));
            addWithMargin(card, text(item.optString("title", ""), 19, TEXT, true), 10);
            addWithMargin(card, text(item.optString("product", "") + "  ·  " +
                    item.optString("version", ""), 13, MUTED, false), 5);
            String description = item.optString("description", "");
            if (!description.isEmpty()) addWithMargin(card, text(description, 14, TEXT, false), 12);
            String author = item.optString("author", "");
            if (!author.isEmpty()) addWithMargin(card, text("Author: " + author, 12, MUTED, false), 12);
        }
    }

    @Override
    protected void onDestroy() {
        ++sessionVersion;
        ++requestVersion;
        bearerToken = "";
        executor.shutdownNow();
        super.onDestroy();
    }
}
