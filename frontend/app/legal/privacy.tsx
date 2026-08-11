import React from "react";
import { View, Text, ScrollView, StyleSheet, Linking, Pressable } from "react-native";
import { Stack } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { theme } from "../../src/lib/theme";
import { PUBLIC_URLS } from "../../src/lib/publicUrls";

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <View style={styles.sect}>
    <Text style={styles.h2}>{title}</Text>
    {children}
  </View>
);

const P = ({ children }: { children: React.ReactNode }) => <Text style={styles.p}>{children}</Text>;
const LI = ({ children }: { children: React.ReactNode }) => <Text style={styles.li}>{"\u2022 "}{children}</Text>;

export default function PrivacyPolicy() {
  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <Stack.Screen options={{ title: "Privacy Policy" }} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 60 }}>
        <Text style={styles.h1}>Privacy Policy</Text>
        <Text style={styles.updated}>Last updated: June 2026</Text>

        <Pressable
          onPress={() => Linking.openURL(PUBLIC_URLS.privacy)}
          testID="privacy-public-mirror"
          style={styles.mirrorBox}
        >
          <Text style={styles.mirrorLabel}>PUBLIC MIRROR</Text>
          <Text style={styles.mirrorUrl}>crewfit.net/privacy</Text>
          <Text style={styles.mirrorNote}>Tap to open the latest version in your browser.</Text>
        </Pressable>

        <Section title="Who we are">
          <P>CrewFit is a fitness and wellbeing platform for aviation professionals. This policy explains how we collect, use, share and protect your personal data. If you have questions, contact us at louis@crewfit.net.</P>
        </Section>

        <Section title="What data we collect">
          <LI>Account information: name, email, encrypted password, role, tier.</LI>
          <LI>Health and fitness data you enter or upload: workouts, sets, personal records, habits, nutrition logs, meal photos, hydration, weight, weekly check-ins, roster and duty schedule.</LI>
          <LI>Content you create: messages to your coach, notes, journal entries, assessment answers.</LI>
          <LI>Technical data: device model, operating system, app version, timezone, IP address (for security), crash reports.</LI>
          <LI>Location data (only if you grant permission): coarse city / country used for travel guidance and roster context.</LI>
        </Section>

        <Section title="How we use it">
          <LI>To provide the CrewFit service: personalised workouts, nutrition guidance, travel-aware suggestions, coach dashboards.</LI>
          <LI>To generate automated insights: photos, text notes and roster data may be sent to trusted inference providers (Anthropic Claude, Google Gemini, OpenAI Whisper) via our processor Emergent. Inference providers do not train on your data.</LI>
          <LI>To send you notifications you have opted into (reminders, check-in prompts).</LI>
          <LI>To improve the service and troubleshoot problems.</LI>
          <LI>To comply with legal obligations.</LI>
        </Section>

        <Section title="Lawful basis (UK / EU GDPR)">
          <LI>Contract — to deliver the service you signed up for.</LI>
          <LI>Legitimate interest — for security, fraud prevention and product improvement.</LI>
          <LI>Consent — for optional features such as location tracking and marketing emails.</LI>
        </Section>

        <Section title="Who we share it with">
          <LI>Your coach (only if you are on a coached plan).</LI>
          <LI>Cloud infrastructure providers: MongoDB Atlas, Cloudflare (CDN + object storage), Emergent (application host and automation gateway).</LI>
          <LI>Inference processors: Anthropic, Google, OpenAI — for the specific inference you request. No profile data is sold or used for advertising.</LI>
          <LI>Legal authorities where legally required.</LI>
        </Section>

        <Section title="International transfers">
          <P>Some processors are based outside the UK / EEA. We use Standard Contractual Clauses and/or UK IDTA safeguards. Contact us for the current sub-processor list.</P>
        </Section>

        <Section title="Retention">
          <P>We keep your data while your account is active. If you request deletion, we mark your account for permanent purge after 30 days (soft-delete grace period). Anonymous, aggregated analytics may be retained indefinitely.</P>
        </Section>

        <Section title="Your rights">
          <LI>Access, correct or download your data (in-app: Settings → Data Export).</LI>
          <LI>Delete your account (in-app: Settings → Delete Account).</LI>
          <LI>Object to or restrict processing.</LI>
          <LI>Withdraw consent at any time.</LI>
          <LI>Complain to the UK ICO or your local supervisory authority.</LI>
        </Section>

        <Section title="Security">
          <P>Passwords are hashed with bcrypt. All traffic is served over HTTPS. Access to production systems is limited and audited. No system is 100% secure — report vulnerabilities to security@crewfit.com.</P>
        </Section>

        <Section title="Children">
          <P>CrewFit is not intended for anyone under 16. We do not knowingly collect data from children.</P>
        </Section>

        <Section title="Changes">
          <P>We will notify you in-app if we make material changes to this policy.</P>
        </Section>

        <Section title="Contact">
          <Pressable onPress={() => Linking.openURL("mailto:louis@crewfit.net")}>
            <Text style={styles.link}>louis@crewfit.net</Text>
          </Pressable>
        </Section>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.surface },
  h1: { color: theme.color.text, fontFamily: theme.font.display, fontSize: 28, marginBottom: 4 },
  updated: { color: theme.color.textDim, fontFamily: theme.font.text, fontSize: 12, marginBottom: 20 },
  mirrorBox: {
    backgroundColor: theme.color.surface2,
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: theme.color.border,
    marginBottom: 20,
  },
  mirrorLabel: {
    color: theme.color.brand,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 1.2,
    marginBottom: 4,
  },
  mirrorUrl: {
    color: theme.color.text,
    fontFamily: theme.font.textSemi,
    fontSize: 16,
    marginBottom: 2,
  },
  mirrorNote: {
    color: theme.color.textDim,
    fontSize: 11,
    fontStyle: "italic",
  },
  sect: { marginBottom: 20 },
  h2: { color: theme.color.text, fontFamily: theme.font.textBold, fontSize: 17, marginBottom: 8 },
  p: { color: theme.color.textMuted, fontFamily: theme.font.text, fontSize: 14, lineHeight: 22, marginBottom: 6 },
  li: { color: theme.color.textMuted, fontFamily: theme.font.text, fontSize: 14, lineHeight: 22, marginBottom: 4 },
  link: { color: theme.color.brand, fontFamily: theme.font.textSemi, fontSize: 15 },
});
