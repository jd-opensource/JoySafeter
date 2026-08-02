package source

import "testing"

func TestParseGenerationNotificationUsesFinalSeparator(t *testing.T) {
	groupKey := "v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	parsedGroup, generation, err := parseGenerationNotification(groupKey + ":42")
	if err != nil {
		t.Fatal(err)
	}
	if parsedGroup != groupKey || generation != 42 {
		t.Fatalf("unexpected notification: group=%q generation=%d", parsedGroup, generation)
	}
}

func TestParseGenerationNotificationRejectsInvalidPayload(t *testing.T) {
	for _, payload := range []string{
		"",
		"group-only",
		"v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:0",
		"v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:not-a-number",
		"v2:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:1",
	} {
		if _, _, err := parseGenerationNotification(payload); err == nil {
			t.Fatalf("expected %q to be rejected", payload)
		}
	}
}

func TestNextBackoffCapsAtFiveSeconds(t *testing.T) {
	value := nextBackoff(4_000_000_000)
	if value != 5_000_000_000 {
		t.Fatalf("backoff = %s", value)
	}
}
