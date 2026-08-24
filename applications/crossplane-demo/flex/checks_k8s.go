package main

import (
	"context"
	"fmt"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

// demoNamespace resolves the namespace the demo resources live in.
func demoNamespace() string { return envDefault("DEMO_NAMESPACE", "crossplane-demo") }

// k8sConfig prefers in-cluster config (the normal case: flex runs as a Pod)
// and falls back to the local kubeconfig so `-once` / tests can run off-cluster.
func k8sConfig() (*rest.Config, error) {
	if cfg, err := rest.InClusterConfig(); err == nil {
		return cfg, nil
	}
	rules := clientcmd.NewDefaultClientConfigLoadingRules()
	return clientcmd.NewNonInteractiveDeferredLoadingClientConfig(rules, &clientcmd.ConfigOverrides{}).ClientConfig()
}

var workflowGVR = schema.GroupVersionResource{
	Group:    "argoproj.io",
	Version:  "v1alpha1",
	Resource: "workflows",
}

// checkArgo: create a Workflow from a workflowTemplateRef and poll its
// status.phase for "Succeeded" (up to ~60s). Uses the dynamic client so we
// don't have to vendor the argo API types.
func checkArgo(ctx context.Context) (string, bool, error) {
	cfg, err := k8sConfig()
	if err != nil {
		return "no kube config (in-cluster or kubeconfig): " + err.Error(), true, nil
	}
	dyn, err := dynamic.NewForConfig(cfg)
	if err != nil {
		return "", false, fmt.Errorf("dynamic client: %w", err)
	}

	ns := demoNamespace()
	tmpl := envDefault("ARGO_WORKFLOWTEMPLATE", "demo-hello")

	spec := map[string]interface{}{
		"workflowTemplateRef": map[string]interface{}{"name": tmpl},
	}
	if sa := env("ARGO_SA"); sa != "" {
		spec["serviceAccountName"] = sa
	}
	wf := &unstructured.Unstructured{Object: map[string]interface{}{
		"apiVersion": "argoproj.io/v1alpha1",
		"kind":       "Workflow",
		"metadata": map[string]interface{}{
			"generateName": "demo-flex-",
			"labels":       map[string]interface{}{"app.kubernetes.io/managed-by": "crossplane-demo-flex"},
		},
		"spec": spec,
	}}

	created, err := dyn.Resource(workflowGVR).Namespace(ns).Create(ctx, wf, metav1.CreateOptions{})
	if err != nil {
		return "", false, fmt.Errorf("create workflow: %w", err)
	}
	name := created.GetName()

	deadline := time.Now().Add(60 * time.Second)
	for {
		got, err := dyn.Resource(workflowGVR).Namespace(ns).Get(ctx, name, metav1.GetOptions{})
		if err != nil {
			return "", false, fmt.Errorf("get workflow %s: %w", name, err)
		}
		phase, _, _ := unstructured.NestedString(got.Object, "status", "phase")
		switch phase {
		case "Succeeded":
			return fmt.Sprintf("workflow %s (template %s) Succeeded", name, tmpl), false, nil
		case "Failed", "Error":
			msg, _, _ := unstructured.NestedString(got.Object, "status", "message")
			return "", false, fmt.Errorf("workflow %s %s: %s", name, phase, msg)
		}
		if time.Now().After(deadline) {
			return "", false, fmt.Errorf("workflow %s did not Succeed within 60s (phase=%q)", name, phase)
		}
		select {
		case <-ctx.Done():
			return "", false, ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
}

// checkCrossplane: the managed Object should have reconciled a ConfigMap into
// the cluster. If it exists, Crossplane did its job.
func checkCrossplane(ctx context.Context) (string, bool, error) {
	cfg, err := k8sConfig()
	if err != nil {
		return "no kube config (in-cluster or kubeconfig): " + err.Error(), true, nil
	}
	cs, err := kubernetes.NewForConfig(cfg)
	if err != nil {
		return "", false, fmt.Errorf("clientset: %w", err)
	}

	ns := demoNamespace()
	name := envDefault("CROSSPLANE_CONFIGMAP", "crossplane-made-this")

	cm, err := cs.CoreV1().ConfigMaps(ns).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return "", false, fmt.Errorf("get configmap %s/%s: %w", ns, name, err)
	}
	return fmt.Sprintf("configmap %s/%s exists (%d keys) — managed Object reconciled", ns, cm.Name, len(cm.Data)), false, nil
}
