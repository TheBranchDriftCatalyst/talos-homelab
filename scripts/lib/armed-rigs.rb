#!/usr/bin/env ruby
# frozen_string_literal: false
#
# armed-rigs.rb — WHICH GPU RIGS ARE ON, derived from the kustomization.
#
# This is the single implementation of one question that four places need to answer
# identically: scripts/check-spot-avail.sh, scripts/gpu-tunnel.sh, and in the sibling
# catalyst-operator repo its Taskfile (llm:*). The operator's Tiltfile deliberately
# keeps its own ~40 lines of Starlark instead of shelling out here — it already has
# read_file/read_yaml_stream builtins, so a subprocess and a Ruby dependency would buy
# nothing. Treat this file as the reference implementation the Tiltfile mirrors.
#
# ── WHY THE KUSTOMIZATION AND NOT A FIELD ─────────────────────────────────────────
# An uncommented `- <claim>.yaml` line in aws/apps/kustomization.yaml IS "that rig is
# on": it is the thing Flux acts on, so it cannot disagree with reality. A `state:`
# field in gpu-profiles.yaml used to carry the same fact, and on 2026-10-02 the two
# drifted — a rig was armed and billing on AWS while the table still read "off"
# (TALOS-cmni). Reading it twice from two places is how that happens.
#
# ── WHY KIND + ROLE AND NOT THE FILENAME ──────────────────────────────────────────
# The previous matchers keyed off a `gpu-node-` filename prefix. Nothing errors when a
# prefix stops matching: the list just comes back empty and every consumer reports
# "off" — the operator silently resolves chat to local Ollama, gpu-tunnel.sh exits,
# check-spot-avail.sh prints a table of zeros — while a GPU bills. A rename was enough
# to trigger that, which made renaming a rig unsafe. So:
#
#   * the KIND (`XGPUInstance`) says "this entry is a rig". Verified to separate
#     cleanly: in aws/apps/ only the rig claims carry it; gpu-profiles.yaml parses to a
#     Hash with no "kind" and is excluded for free, and the rest are
#     User/Role/ServiceAccount/XInstance/XFargateApp/ServiceLinkedRole.
#   * the ROLE label (`catalyst.io/gpu-role: llm|image`) says WHICH rig, because a
#     token box and a pixel box are both `kind: XGPUInstance` and the kind alone cannot
#     tell them apart. Without it, an image rig would be handed to chat as an LLM
#     endpoint, or an armed LLM rig would be hidden from the image path.
#
# A claim that is armed but malformed ABORTS rather than being skipped. Skipping is
# what turns a money question into silence, and every caller here is reading this to
# decide whether something is costing $2-10/hr.
#
# Usage as a library:
#   require_relative "lib/armed-rigs"
#   ArmedRigs.names(apps_dir, role: "llm")   # => ["inference-node"]
#   ArmedRigs.all(apps_dir)                  # => [{"name"=>…, "role"=>…, "file"=>…}]
#
# Usage as a CLI (one name per line, empty output when nothing is armed):
#   scripts/lib/armed-rigs.rb <apps_dir> [role]

require "yaml"

module ArmedRigs
  KIND       = "XGPUInstance".freeze
  ROLE_LABEL = "catalyst.io/gpu-role".freeze
  ROLES      = %w[llm image].freeze

  # Every armed claim of kind XGPUInstance, in kustomization order.
  #
  # Order matters to callers that take the first element, so it is deliberately the
  # file's own order rather than sorted.
  def self.all(apps_dir)
    kust = File.join(apps_dir, "kustomization.yaml")
    return [] unless File.exist?(kust)

    out = []
    File.readlines(kust).each do |line|
      entry = line.strip
      # Commented lines start with '#', so the off position is excluded by construction.
      next unless entry.start_with?("- ")
      # Strip a trailing `# TALOS-xxxx`-style note BEFORE testing the suffix. Annotating
      # a resource line is the convention in that directory (see aws/kustomization.yaml),
      # and requiring the line to end in `.yaml` reads an annotated-but-ARMED rig as off:
      # `- inference-node.yaml  # ARMED, ~$2.24/hr` would have billed silently.
      entry = entry.delete_prefix("- ").split("#").first.to_s.strip
      next unless entry.end_with?(".yaml")

      path = File.join(apps_dir, entry)
      next unless File.exist?(path)

      begin
        docs = YAML.load_stream(File.read(path))
      rescue Psych::SyntaxError => e
        abort "armed-rigs: #{entry} is armed but is not parseable YAML: #{e.message}"
      end

      docs.each do |doc|
        next unless doc.is_a?(Hash) && doc["kind"] == KIND

        meta = doc["metadata"] || {}
        role = ((meta["labels"] || {})[ROLE_LABEL]).to_s
        if role.empty?
          abort "armed-rigs: #{entry} is an ARMED #{KIND} with no #{ROLE_LABEL} label, " \
                "so nothing can tell whether it serves tokens or pixels. Add " \
                "`#{ROLE_LABEL}: llm` (or `image`) to its metadata.labels."
        end
        unless ROLES.include?(role)
          abort "armed-rigs: #{entry} has #{ROLE_LABEL}: #{role.inspect}, " \
                "which is not one of #{ROLES.join(' | ')}."
        end

        # spec.instanceName is the AWS-FACING identity: it becomes the box's tag:Name
        # and the derived `<name>-fleet` managed resource, so it is what the relay and
        # gpu-tunnel.sh resolve by. gpu-profiles.yaml's rigs[].name must equal it.
        name = ((doc["spec"] || {})["instanceName"] || meta["name"]).to_s
        abort "armed-rigs: #{entry} is an ARMED #{KIND} with no spec.instanceName" if name.empty?

        out << { "name" => name, "role" => role, "file" => entry }
      end
    end
    out
  end

  # Names of armed rigs, optionally filtered to one role.
  def self.names(apps_dir, role: nil)
    all(apps_dir).select { |r| role.nil? || r["role"] == role }.map { |r| r["name"] }
  end
end

if $PROGRAM_NAME == __FILE__
  if ARGV.empty?
    warn "usage: #{File.basename($PROGRAM_NAME)} <aws/apps dir> [#{ArmedRigs::ROLES.join('|')}]"
    exit 2
  end
  puts ArmedRigs.names(ARGV[0], role: ARGV[1])
end
