package com.goreecloud.changelogs;

import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Self-hosted HTTPS account login and read-only changelog viewer.
 * Session is kept in volatile memory only; no WebView, cleartext downgrade,
 * TLS certificate bypass, redirect, analytics or persistent credentials.
 */
public final class HostedActivity extends Activity {
    private static final int BACKGROUND = Color.rgb(13, 18, 32);
    private static final int PANEL = Color.rgb(28, 37, 57);
    private static final int TEXT = Color.rgb(241, 246, 252);
    private static final int SOFT = Color.rgb(183, 199, 220);
    private static final int ACCENT = Color.rgb(183, 170, 255);
    private static final int MAX_BODY = 512 * 1024;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();

    private EditText serverInput, usernameInput, passwordInput, productInput;
    private TextView status, identity;
    private LinearLayout entries, loginPanel, workspace;
    private Button signIn, loadMore;
    private String origin = "", token = "";
    private long sessionGeneration = 0, requestGeneration = 0;
    private int offset = 0;
    private boolean more = false;

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private TextView text(String value, int size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextColor(color);
        view.setTextSize(size);
        view.setTypeface(Typeface.DEFAULT, bold ? Typeface.BOLD : Typeface.NORMAL);
        return view;
    }

    private EditText field(String hint, int type, boolean secret) {
        EditText input = new EditText(this);
        input.setHint(hint);
        input.setTextColor(TEXT);
        input.setHintTextColor(SOFT);
        input.setTextSize(16);
        input.setSingleLine(true);
        input.setInputType(type);
        input.setPadding(dp(14), dp(10), dp(14), dp(10));
        if (secret) {
            input.setSaveEnabled(false);
            input.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        }
        return input;
    }

    private void add(LinearLayout parent, View child, int margin) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(margin);
        parent.addView(child, params);
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(BACKGROUND);
        getWindow().setNavigationBarColor(BACKGROUND);
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BACKGROUND);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(22), dp(32), dp(22), dp(32));
        scroll.addView(root);
        setContentView(scroll);
        add(root, text("GOREECLOUD / CHANGELOGS", 13, ACCENT, true), 0);
        add(root, text("Your shared history", 31, TEXT, true), 16);
        add(root, text("Sign in to the Changelogs server you own.", 15, SOFT, false), 7);
        loginPanel = new LinearLayout(this);
        loginPanel.setOrientation(LinearLayout.VERTICAL);
        add(root, loginPanel, 24);
        serverInput = field("https://changelogs.yourdomain.com",
            InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI, false);
        add(loginPanel, serverInput, 0);
        usernameInput = field("Username",
            InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_NORMAL, false);
        add(loginPanel, usernameInput, 10);
        passwordInput = field("Password",
            InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD, true);
        add(loginPanel, passwordInput, 10);
        signIn = new Button(this);
        signIn.setText("Sign in");
        signIn.setAllCaps(false);
        signIn.setTextColor(BACKGROUND);
        signIn.setBackgroundTintList(ColorStateList.valueOf(ACCENT));
        add(loginPanel, signIn, 14);
        signIn.setOnClickListener(v -> signIn());

        workspace = new LinearLayout(this);
        workspace.setOrientation(LinearLayout.VERTICAL);
        workspace.setVisibility(View.GONE);
        add(root, workspace, 24);
        identity = text("", 14, SOFT, false);
        add(workspace, identity, 0);
        productInput = field("Filter product (optional)",
            InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_NORMAL, false);
        add(workspace, productInput, 13);
        Button refresh = new Button(this);
        refresh.setText("Refresh");
        refresh.setAllCaps(false);
        add(workspace, refresh, 12);
        refresh.setOnClickListener(v -> readPage(false));
        Button signOut = new Button(this);
        signOut.setText("Sign out");
        signOut.setAllCaps(false);
        add(workspace, signOut, 6);
        signOut.setOnClickListener(v -> signOut());
        entries = new LinearLayout(this);
        entries.setOrientation(LinearLayout.VERTICAL);
        add(workspace, entries, 16);
        loadMore = new Button(this);
        loadMore.setText("Load more");
        loadMore.setAllCaps(false);
        loadMore.setVisibility(View.GONE);
        add(workspace, loadMore, 12);
        loadMore.setOnClickListener(v -> {
            if (more) readPage(true);
        });
        status = text("Use the trusted HTTPS address of your self-hosted server.", 13, SOFT, false);
        status.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);
        add(root, status, 24);
    }

    private String validateOrigin(String supplied) throws Exception {
        URI address = new URI(supplied);
        if (!"https".equals(address.getScheme()) ||
            address.getHost() == null || address.getHost().isEmpty() ||
            address.getRawUserInfo() != null || address.getRawQuery() != null ||
            address.getRawFragment() != null ||
            (address.getRawPath() != null && !address.getRawPath().isEmpty() &&
             !"/".equals(address.getRawPath())) ||
            address.getPort() == 0 || address.getPort() > 65535 ||
            supplied.length() > 1024) {
            throw new IllegalArgumentException("Use a trusted HTTPS server origin.");
        }
        return supplied.endsWith("/") ? supplied.substring(0, supplied.length() - 1) : supplied;
    }

    private JSONObject call(String base, String route, String bearer, JSONObject body) throws Exception {
        URL url = new URL(base + route);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setInstanceFollowRedirects(false);
        conn.setConnectTimeout(5000);
        conn.setReadTimeout(8000);
        conn.setUseCaches(false);
        conn.setRequestProperty("Accept", "application/json");
        if (!bearer.isEmpty()) conn.setRequestProperty("Authorization", "Bearer " + bearer);
        conn.setRequestMethod(body == null ? "GET" : "POST");
        if (body != null) {
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
        }
        try {
            if (body != null) {
                byte[] data = body.toString().getBytes(StandardCharsets.UTF_8);
                if (data.length > 8192) throw new IllegalStateException("Login request too large.");
                conn.setFixedLengthStreamingMode(data.length);
                try (OutputStream out = conn.getOutputStream()) { out.write(data); }
            }
            int result = conn.getResponseCode();
            if (result != 200) {
                throw new IllegalStateException(
                    result == 401 || result == 403 ? "Authentication or permissions rejected." :
                    "Server request failed (" + result + ").");
            }
            try (InputStream in = conn.getInputStream();
                 ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[4096];
                int count;
                while ((count = in.read(buffer)) != -1) {
                    if (bytes.size() + count > MAX_BODY) {
                        throw new IllegalStateException("Response too large; narrow filters.");
                    }
                    bytes.write(buffer, 0, count);
                }
                return new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
            }
        } finally {
            conn.disconnect();
        }
    }

    private void signIn() {
        final String server;
        try {
            server = validateOrigin(serverInput.getText().toString().trim());
        } catch (Exception error) {
            status.setText("Enter a trusted HTTPS server address.");
            return;
        }
        final String user = usernameInput.getText().toString().trim();
        final String password = passwordInput.getText().toString();
        passwordInput.setText("");
        if (user.isEmpty() || password.isEmpty()) {
            status.setText("Enter your username and password.");
            return;
        }
        final long session = ++sessionGeneration;
        ++requestGeneration;
        signIn.setEnabled(false);
        status.setText("Signing in securely…");
        worker.execute(() -> {
            try {
                JSONObject credentials = new JSONObject();
                credentials.put("username", user);
                credentials.put("password", password);
                JSONObject response = call(server, "/v1/auth/token", "", credentials);
                String newToken = response.getString("token");
                if (newToken.length() < 32 || newToken.length() > 256) {
                    throw new IllegalStateException("Invalid authentication response.");
                }
                String label = response.optString("username", user);
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed() || session != sessionGeneration) return;
                    origin = server;
                    token = newToken;
                    offset = 0; more = false;
                    loginPanel.setVisibility(View.GONE);
                    workspace.setVisibility(View.VISIBLE);
                    identity.setText("Signed in as " + label);
                    signIn.setEnabled(true);
                    readPage(false);
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed() || session != sessionGeneration) return;
                    signIn.setEnabled(true);
                    status.setText("Sign-in failed. Verify HTTPS, account and server availability.");
                });
            }
        });
    }

    private void readPage(boolean append) {
        if (origin.isEmpty() || token.isEmpty()) return;
        final long session = sessionGeneration;
        final long sequence = ++requestGeneration;
        final String server = origin, access = token;
        final int start = append ? offset : 0;
        final String product = productInput.getText().toString().trim();
        loadMore.setEnabled(false);
        status.setText("Loading server history…");
        worker.execute(() -> {
            try {
                String route = "/v1/entries?limit=30&offset=" + start;
                if (!product.isEmpty()) {
                    route += "&product=" + java.net.URLEncoder.encode(
                        product, StandardCharsets.UTF_8.name());
                }
                JSONObject data = call(server, route, access, null);
                JSONArray rows = data.getJSONArray("entries");
                final boolean continues = data.optBoolean("has_more", false);
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed() || session != sessionGeneration ||
                        sequence != requestGeneration) return;
                    showEntries(rows, append);
                    offset = start + rows.length();
                    more = continues;
                    loadMore.setVisibility(continues ? View.VISIBLE : View.GONE);
                    loadMore.setEnabled(continues);
                    status.setText("Changelogs loaded from your server.");
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed() || session != sessionGeneration ||
                        sequence != requestGeneration) return;
                    loadMore.setEnabled(more);
                    status.setText("Unable to load changes. Check sign-in and server.");
                });
            }
        });
    }

    private void showEntries(JSONArray rows, boolean append) {
        if (!append) entries.removeAllViews();
        if (rows.length() == 0 && !append) {
            add(entries, text("No changes found.", 15, SOFT, false), 10);
        }
        for (int i = 0; i < rows.length(); i++) {
            JSONObject item = rows.optJSONObject(i);
            if (item == null) continue;
            LinearLayout card = new LinearLayout(this);
            card.setOrientation(LinearLayout.VERTICAL);
            card.setPadding(dp(15), dp(15), dp(15), dp(15));
            card.setBackgroundTintList(null);
            card.setBackgroundColor(PANEL);
            add(entries, card, 12);
            add(card, text(item.optString("kind", "change").toUpperCase(java.util.Locale.ROOT)
                + " · " + item.optString("released_at", ""), 12, ACCENT, true), 0);
            add(card, text(item.optString("title", ""), 19, TEXT, true), 10);
            add(card, text(item.optString("product", "") + " · " +
                item.optString("version", ""), 13, SOFT, false), 6);
            String details = item.optString("description", "");
            if (!details.isEmpty()) add(card, text(details, 14, TEXT, false), 10);
        }
    }

    private void signOut() {
        // Discard local credentials first. The server's opaque token expires
        // within 12 hours; a future revision should complete remote revocation.
        ++sessionGeneration;
        ++requestGeneration;
        token = "";
        origin = "";
        entries.removeAllViews();
        offset = 0; more = false;
        loadMore.setVisibility(View.GONE);
        workspace.setVisibility(View.GONE);
        loginPanel.setVisibility(View.VISIBLE);
        signIn.setEnabled(true);
        passwordInput.setText("");
        status.setText("Signed out on this device. Server session may remain active until expiry.");
    }

    @Override protected void onDestroy() {
        ++sessionGeneration;
        ++requestGeneration;
        token = "";
        origin = "";
        worker.shutdownNow();
        super.onDestroy();
    }
}
